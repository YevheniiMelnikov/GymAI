from typing import Any
from urllib.parse import urljoin

import orjson
from loguru import logger

from core.services.internal.api_client import APIClient
from core.exceptions import UserServiceError
from core.internal_http import build_internal_hmac_auth_headers
from config.app_settings import settings


class DietService(APIClient):
    async def save_plan(self, profile_id: int, request_id: str, plan: dict[str, Any]) -> int | None:
        url = urljoin(self.api_url, "internal/diets/")
        logger.info(f"event=diet_save_request url={url} request_id={request_id} profile_id={profile_id}")

        data = {
            "profile_id": profile_id,
            "request_id": request_id,
            "plan": plan,
        }

        body = orjson.dumps(data)
        headers = build_internal_hmac_auth_headers(
            key_id=settings.INTERNAL_KEY_ID,
            secret_key=settings.INTERNAL_API_KEY,
            body=body,
        )
        headers["Content-Type"] = "application/json"

        try:
            status_code, response = await self._api_request("post", url, body_bytes=body, headers=headers)

            if status_code not in {200, 201}:
                logger.error(f"Failed to save diet plan for profile_id={profile_id}: {response}")
                raise UserServiceError(f"Failed to save diet plan, received status {status_code}: {response}")

            response = response or {}
            diet_id = response.get("diet_id")
            return int(diet_id) if diet_id is not None else None

        except UserServiceError as e:
            logger.error(f"Error while saving diet plan for profile_id={profile_id}: {str(e)}")
            raise

        except Exception as e:  # noqa: BLE001
            logger.exception(f"Unexpected error while saving diet plan for profile_id={profile_id}: {str(e)}")
            raise UserServiceError(f"Unexpected error occurred while saving diet plan: {str(e)}") from e
