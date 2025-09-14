from json import JSONDecodeError
import asyncio
from typing import Optional, Any, Protocol
from decimal import Decimal
import httpx
from loguru import logger

from core.exceptions import UserServiceError


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
        headers: Optional[dict] = None,
        timeout: int | None = None,
    ) -> tuple[int, Optional[dict]]:
        headers = headers or {}
        if self.use_default_auth and self.api_key:
            headers.setdefault("Authorization", f"Bearer {self.api_key}")

        delay = self.initial_delay
        data = self._json_safe(data)
        timeout = timeout or self.default_timeout

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = await self.client.request(method, url, json=data, headers=headers, timeout=timeout)

                if resp.is_success:
                    if resp.headers.get("content-type", "").startswith("application/json"):
                        try:
                            return resp.status_code, resp.json()
                        except JSONDecodeError:
                            logger.warning(f"Failed to decode JSON from response for {url}")
                            return resp.status_code, None
                    return resp.status_code, None

                error_data: Optional[dict]
                if resp.headers.get("content-type", "").startswith("application/json"):
                    try:
                        error_data = resp.json()
                    except JSONDecodeError:
                        error_data = {"error": resp.text}
                else:
                    error_data = {"error": resp.text}

                if resp.status_code == 404:
                    return resp.status_code, error_data

                if resp.status_code == 403:
                    logger.error(
                        f"Request to {url} failed with HTTP=403 Forbidden. Verify API key. Response: {error_data}"
                    )
                else:
                    logger.error(f"Request to {url} failed with HTTP={resp.status_code}, response: {error_data}")

                if resp.status_code >= 500 or resp.status_code == 429:
                    raise httpx.HTTPStatusError("Retryable error", request=resp.request, response=resp)
                return resp.status_code, error_data

            except (httpx.HTTPStatusError, httpx.HTTPError) as e:
                logger.warning(f"Attempt {attempt} failed: {type(e).__name__}: {e!r}. Retrying in {delay:.1f}s...")
                if attempt == self.max_retries:
                    raise UserServiceError(
                        f"Request to {url} failed after {attempt} attempts: {type(e).__name__}: {e!r}"
                    ) from e
                await asyncio.sleep(delay)
                delay = min(delay * self.backoff_factor, self.max_delay)

            except Exception as e:  # noqa: BLE001
                logger.exception("Unexpected error occurred")
                raise UserServiceError(f"Unexpected error: {e}") from e

        return 500, None
