from json import JSONDecodeError
import asyncio
from typing import Optional, ClassVar, Any
from decimal import Decimal
import httpx
from loguru import logger

from core.exceptions import UserServiceError
from config.app_settings import settings


class APIClient:
    api_url = settings.API_URL
    api_key = settings.API_KEY
    use_default_auth = True

    client: ClassVar[Any | None] = None
    _clients: ClassVar[dict[int, httpx.AsyncClient]] = {}

    max_retries = settings.API_MAX_RETRIES
    initial_delay = settings.API_RETRY_INITIAL_DELAY
    backoff_factor = settings.API_RETRY_BACKOFF_FACTOR
    max_delay = settings.API_RETRY_MAX_DELAY

    @classmethod
    def _get_client(cls, timeout: int) -> httpx.AsyncClient:
        """Return a configured client, using a stub if provided for tests."""
        if cls.client is not None:
            return cls.client

        loop = asyncio.get_running_loop()
        key = id(loop)

        client = cls._clients.get(key)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(timeout=timeout)
            cls._clients[key] = client
        return client

    @classmethod
    async def aclose(cls) -> None:
        """Close all cached clients."""
        for key, client in list(cls._clients.items()):
            try:
                await client.aclose()
            except Exception:
                logger.exception("Failed to close httpx client for loop %s", key)
            finally:
                cls._clients.pop(key, None)

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

    @classmethod
    async def _api_request(
        cls,
        method: str,
        url: str,
        data: Optional[dict] = None,
        headers: Optional[dict] = None,
        timeout: int = settings.API_TIMEOUT,
    ) -> tuple[int, Optional[dict]]:
        headers = headers or {}
        if cls.use_default_auth and cls.api_key:
            headers.setdefault("Authorization", f"Bearer {cls.api_key}")

        delay = cls.initial_delay
        data = cls._json_safe(data)

        for attempt in range(1, cls.max_retries + 1):
            try:
                client = cls._get_client(timeout)
                resp = await client.request(method, url, json=data, headers=headers)

                if resp.is_success:
                    content_type = getattr(resp, "headers", {}).get("content-type", "")
                    try:
                        if content_type.startswith("application/json") or not content_type:
                            return resp.status_code, resp.json()
                    except JSONDecodeError:
                        logger.warning("Failed to decode JSON from response for %s", url)
                    return resp.status_code, None

                error_data: Optional[dict]
                if getattr(resp, "headers", {}).get("content-type", "").startswith("application/json"):
                    try:
                        error_data = resp.json()
                    except JSONDecodeError:
                        error_data = {"error": resp.text}
                else:
                    error_data = {"error": resp.text}

                if resp.status_code == 404:
                    return resp.status_code, error_data

                logger.error("Request to %s failed with HTTP=%s, response: %s", url, resp.status_code, error_data)

                if resp.status_code >= 500 or resp.status_code == 429:
                    raise httpx.HTTPStatusError("Retryable error", request=resp.request, response=resp)
                return resp.status_code, error_data

            except (httpx.HTTPStatusError, httpx.HTTPError) as e:
                logger.warning("Attempt %s failed: %s: %r. Retrying in %.1fs...", attempt, type(e).__name__, e, delay)
                if attempt == cls.max_retries:
                    raise UserServiceError(
                        f"Request to {url} failed after {attempt} attempts: {type(e).__name__}: {e!r}"
                    ) from e
                await asyncio.sleep(delay)
                delay = min(delay * cls.backoff_factor, cls.max_delay)

            except Exception as e:
                logger.exception("Unexpected error occurred")
                raise UserServiceError(f"Unexpected error: {e}") from e

        return 500, None
