from json import JSONDecodeError
import asyncio
from typing import Optional

import httpx
from loguru import logger

from core.exceptions import UserServiceError
from config.env_settings import settings


class APIClient:
    api_url = settings.API_URL
    api_key = settings.API_KEY
    client = httpx.AsyncClient(timeout=settings.API_TIMEOUT)

    max_retries = settings.API_MAX_RETRIES
    initial_delay = settings.API_RETRY_INITIAL_DELAY
    backoff_factor = settings.API_RETRY_BACKOFF_FACTOR
    max_delay = settings.API_RETRY_MAX_DELAY

    @classmethod
    async def _api_request(
        cls,
        method: str,
        url: str,
        data: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> tuple[int, Optional[dict]]:
        headers = headers or {}
        if cls.api_key:
            headers.setdefault("Authorization", f"Bearer {cls.api_key}")

        delay = cls.initial_delay

        for attempt in range(1, cls.max_retries + 1):
            try:
                response = await cls.client.request(method, url, json=data, headers=headers)

                if response.is_success:
                    try:
                        return response.status_code, response.json()
                    except JSONDecodeError:
                        logger.warning(f"Failed to decode JSON from response for {url}")
                        return response.status_code, None

                try:
                    error_data = response.json()
                except JSONDecodeError:
                    error_data = {"error": response.text}

                if response.status_code == 404:
                    return response.status_code, error_data

                logger.error(f"Request to {url} failed with HTTP={response.status_code}")
                if response.status_code >= 500 or response.status_code == 429:
                    raise httpx.HTTPStatusError("Retryable error", request=response.request, response=response)
                return response.status_code, error_data

            except (httpx.HTTPStatusError, httpx.HTTPError) as e:
                logger.warning(f"Attempt {attempt} failed: {e}. Retrying in {delay:.1f}s...")
                if attempt == cls.max_retries:
                    raise UserServiceError(f"Request to {url} failed after {attempt} attempts: {e}") from e
                await asyncio.sleep(delay)
                delay = min(delay * cls.backoff_factor, cls.max_delay)

            except Exception as e:
                logger.exception("Unexpected error occurred")
                raise UserServiceError(f"Unexpected error: {e}") from e

        return 500, None
