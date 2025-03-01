from json import JSONDecodeError
from urllib.parse import urljoin

import httpx
from common.logger import logger

from core.exceptions import UserServiceError
from common.settings import settings


class APIClient:
    api_url = settings.API_URL
    api_key = settings.API_KEY
    client = httpx.AsyncClient()

    @classmethod
    async def _api_request(cls, method: str, url: str, data: dict | None = None, headers: dict = None) -> tuple:
        logger.debug(f"Executing {method.upper()} request to {url} with params: {data}")
        try:
            response = await cls.client.request(method, url, json=data, headers=headers)
            if response.is_success:
                try:
                    json_data = response.json()
                    return response.status_code, json_data
                except JSONDecodeError:
                    logger.warning(f"Failed to decode JSON from response for {url}")
                    return response.status_code, None
            else:
                try:
                    error_data = response.json()
                except JSONDecodeError:
                    error_data = {"error": response.text}

                if response.status_code == 404:
                    logger.info(f"Request to {url} returned 404: {error_data}")
                else:
                    logger.error(
                        f"Request to {url} failed with status code {response.status_code} and response: {error_data}"
                    )

                return response.status_code, error_data

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error occurred: {e}")
            raise UserServiceError(f"HTTP request failed with status {e.response.status_code}: {e}") from e
        except httpx.HTTPError as e:
            logger.exception("HTTP error occurred")
            raise UserServiceError(f"HTTP request failed: {e}") from e
        except Exception as e:
            logger.exception("Unexpected error occurred")
            raise UserServiceError(f"Unexpected error occurred: {e}") from e

    @classmethod
    async def send_welcome_email(cls, email: str, username: str) -> bool:
        url = urljoin(cls.api_url, "api/v1/send-welcome-email/")
        data = {"email": email, "username": username}
        status_code, response = await cls._api_request(
            "post", url, data=data, headers={"Authorization": f"Api-Key {cls.api_key}"}
        )
        if status_code == 200:
            return True
        logger.error(f"Failed to send welcome email. Status code: {status_code}, response: {response}")
        return False
