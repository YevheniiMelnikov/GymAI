from json import JSONDecodeError
from urllib.parse import urljoin

import httpx
import loguru

from core.exceptions import UserServiceError
from core.settings import settings

logger = loguru.logger


class APIService:
    def __init__(self):
        self.api_url = settings.API_URL
        self.api_key = settings.API_KEY
        self.client = httpx.AsyncClient()

    async def _api_request(self, method: str, url: str, data: dict | None = None, headers: dict = None) -> tuple:
        logger.debug(f"Executing {method.upper()} request to {url} with params: {data}")
        try:
            response = await self.client.request(method, url, json=data, headers=headers)
            if response.is_success:
                try:
                    json_data = response.json()
                    return response.status_code, json_data
                except JSONDecodeError:
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
        except httpx.HTTPError as e:
            logger.exception("HTTP error occurred")
            raise UserServiceError(f"HTTP request failed: {e}") from e
        except Exception as e:
            logger.exception("Unexpected error occurred")
            raise UserServiceError(f"Unexpected error occurred: {e}") from e

    async def send_welcome_email(self, email: str, username: str) -> bool:
        url = urljoin(self.api_url, "api/v1/send-welcome-email/")
        data = {"email": email, "username": username}
        status_code, response = await self._api_request(
            "post", url, data=data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200:
            return True
        logger.error(f"Failed to send welcome email. Status code: {status_code}, response: {response}")
        return False


api_service = APIService()
