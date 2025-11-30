import asyncio
from decimal import Decimal
from json import JSONDecodeError, loads
from typing import Any, Optional, Protocol

import httpx
from loguru import logger

from core.exceptions import UserServiceError


class APIClientHTTPError(UserServiceError):
    def __init__(
        self,
        status: int,
        text: str,
        *,
        method: str,
        url: str,
        retryable: bool = False,
        reason: str | None = None,
    ) -> None:
        self.status = status
        self.text = text
        self.retryable = retryable
        self.reason = reason
        super().__init__(
            f"HTTP {status} on {method.upper()} {url}: {text}" if text else f"HTTP {status} on {method.upper()} {url}"
        )


class APIClientTransportError(UserServiceError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class APISettings(Protocol):
    API_URL: str
    API_KEY: str
    API_MAX_RETRIES: int
    API_RETRY_INITIAL_DELAY: float
    API_RETRY_BACKOFF_FACTOR: float
    API_RETRY_MAX_DELAY: float
    API_TIMEOUT: int
    AI_COACH_URL: str
    AI_COACH_TIMEOUT: int
    AI_COACH_REFRESH_USER: str
    AI_COACH_REFRESH_PASSWORD: str
    AI_COACH_INTERNAL_KEY_ID: str
    AI_COACH_INTERNAL_API_KEY: str
    INTERNAL_KEY_ID: str
    INTERNAL_API_KEY: str


class APIClient:
    def __init__(self, client: httpx.AsyncClient, settings: APISettings) -> None:
        self.client = client
        self.settings = settings
        self.api_url = getattr(settings, "API_URL", "").rstrip("/")
        self.api_key = getattr(settings, "API_KEY", "")
        self.use_default_auth = True
        self.max_retries = getattr(settings, "API_MAX_RETRIES", 0)
        self.initial_delay = getattr(settings, "API_RETRY_INITIAL_DELAY", 0.0)
        self.backoff_factor = getattr(settings, "API_RETRY_BACKOFF_FACTOR", 0.0)
        self.max_delay = getattr(settings, "API_RETRY_MAX_DELAY", 0.0)
        self.default_timeout = getattr(settings, "API_TIMEOUT", 0)

    async def aclose(self) -> None:
        try:
            await self.client.aclose()
        except Exception:  # pragma: no cover - best effort
            logger.exception("Failed to close httpx client")

    @staticmethod
    def _json_safe(obj: Optional[dict]) -> Any:
        """Convert Decimals in payload to primitive types for JSON."""
        if obj is None:
            return None

        def convert(value):
            if isinstance(value, Decimal):
                return int(value) if value == value.to_integral() else str(value)
            if isinstance(value, dict):
                return {k: convert(v) for k, v in value.items()}
            if isinstance(value, list):
                return [convert(v) for v in value]
            return value

        return convert(obj)

    def _build_url(self, path: str) -> str:
        base = self.api_url
        part = path.lstrip("/")
        tail = base.split("://", 1)[-1]
        if tail.endswith("/api") and part.startswith("api/"):
            part = part[4:]
        return f"{base}/{part}"

    async def _api_request(
        self,
        method: str,
        url: str,
        data: Optional[dict] = None,
        *,
        body_bytes: bytes | None = None,
        headers: Optional[dict] = None,
        timeout: int | None = None,
        allow_statuses: set[int] | None = None,
        client: httpx.AsyncClient | None = None,
        retry_server_errors: bool = True,
    ) -> tuple[int, Any | None]:
        headers = headers or {}
        if self.use_default_auth and self.api_key:
            headers.setdefault("Authorization", f"Bearer {self.api_key}")

        # body_bytes is raw content (e.g. pre-serialized JSON used for HMAC); when present we skip json serialization
        json_payload = None if body_bytes is not None else self._json_safe(data)
        timeout_value = timeout or self.default_timeout or None
        allowed = allow_statuses or set()
        attempts = max(1, self.max_retries + 1)
        delay = self.initial_delay

        for attempt in range(1, attempts + 1):
            try:
                request_kwargs: dict[str, Any] = {
                    "headers": headers,
                    "timeout": timeout_value,
                }
                if body_bytes is not None:
                    request_kwargs["content"] = body_bytes
                else:
                    request_kwargs["json"] = json_payload

                if client is not None:
                    response = await client.request(
                        method,
                        url,
                        **request_kwargs,
                    )
                else:
                    limits = httpx.Limits(max_connections=50, max_keepalive_connections=10)
                    base_url_candidate = getattr(self, "base_url", None) or getattr(self, "api_url", None)
                    base_url_value = str(base_url_candidate or "")
                    async with httpx.AsyncClient(
                        base_url=base_url_value, timeout=timeout_value, limits=limits
                    ) as _client:
                        response = await _client.request(
                            method,
                            url,
                            **request_kwargs,
                        )

                if response.status_code in allowed:
                    return response.status_code, self._parse_response_json(response)

                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code if exc.response else response.status_code
                    body = exc.response.text if exc.response else ""
                    reason = self._extract_reason(body)
                    retryable = status == 429 or (
                        retry_server_errors and status >= 500 and reason not in {"timeout", "knowledge_base_empty"}
                    )
                    if retryable:
                        if attempt < attempts:
                            logger.warning(
                                f"Retrying {method.upper()} {url} after HTTP {status} (attempt {attempt}/{attempts})"
                            )
                            await self._sleep(delay)
                            delay = self._next_delay(delay)
                            continue
                    raise APIClientHTTPError(
                        status,
                        body,
                        method=method,
                        url=url,
                        retryable=retryable,
                        reason=reason,
                    ) from exc

                return response.status_code, self._parse_response_json(response)

            except APIClientHTTPError:
                raise

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response else None
                body = exc.response.text if exc.response else ""
                reason = self._extract_reason(body)
                retryable = status == 429 or (
                    retry_server_errors
                    and status is not None
                    and status >= 500
                    and reason not in {"timeout", "knowledge_base_empty"}
                )
                if retryable and attempt < attempts:
                    logger.warning(
                        f"Retrying {method.upper()} {url} after HTTP {status} (attempt {attempt}/{attempts})"
                    )
                    await self._sleep(delay)
                    delay = self._next_delay(delay)
                    continue
                raise APIClientHTTPError(
                    status or 0,
                    body,
                    method=method,
                    url=url,
                    retryable=retryable,
                    reason=reason,
                ) from exc

            except httpx.RequestError as exc:
                if attempt >= attempts:
                    raise APIClientTransportError(f"{type(exc).__name__} on {method.upper()} {url}: {exc}") from exc
                logger.warning(
                    f"Retrying {method.upper()} {url} after transport error {type(exc).__name__} "
                    f"(attempt {attempt}/{attempts})"
                )
                await self._sleep(delay)
                delay = self._next_delay(delay)

            except Exception as exc:  # noqa: BLE001
                logger.exception(f"Unexpected error during {method.upper()} {url}: {exc}")
                raise APIClientTransportError(f"Unexpected error on {method.upper()} {url}: {exc}") from exc

        raise APIClientTransportError(f"Exhausted retries for {method.upper()} {url}")

    @staticmethod
    async def _sleep(delay: float) -> None:
        if delay > 0:
            await asyncio.sleep(delay)

    def _next_delay(self, current: float) -> float:
        if current <= 0:
            return self.initial_delay or 0.0
        next_delay = current * self.backoff_factor
        if self.max_delay:
            next_delay = min(next_delay, self.max_delay)
        return next_delay

    @staticmethod
    def _parse_response_json(response: httpx.Response) -> Any | None:
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            try:
                payload = response.json()
            except JSONDecodeError:
                logger.warning(f"Failed to decode JSON response from {response.request.url}")
                return None
            return payload
        return None

    @staticmethod
    def _extract_reason(body: str) -> str | None:
        if not body:
            return None
        try:
            data = loads(body)
        except JSONDecodeError:
            return None
        if isinstance(data, dict):
            reason = data.get("reason")
            if isinstance(reason, str):
                return reason
            detail = data.get("detail")
            if isinstance(detail, dict):
                nested_reason = detail.get("reason")
                if isinstance(nested_reason, str):
                    return nested_reason
        return None
