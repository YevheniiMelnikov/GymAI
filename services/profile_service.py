from typing import Any

import loguru

from services.backend_service import BackendService
from common.models import Profile
from common.encrypter import encrypter as enc, Encrypter

logger = loguru.logger


class ProfileService(BackendService):
    def __init__(self, encrypter: Encrypter):
        super().__init__()
        self.encrypter = encrypter

    async def get_profile(self, profile_id: int) -> dict[str, Any] | None:
        url = f"{self.backend_url}api/v1/persons/{profile_id}/"
        status_code, user_data = await self._api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200 and user_data:
            return user_data

        logger.info(f"Failed to retrieve email for profile_id {profile_id}. HTTP status: {status_code}")
        return None

    async def get_profile_by_username(self, username: str) -> Profile | None:
        url = f"{self.backend_url}api/v1/persons/{username}/"
        status_code, profile_data = await self._api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200:
            return Profile.from_dict(profile_data)

        logger.info(f"Failed to retrieve profile for {username}. HTTP status: {status_code}")
        return None

    async def get_profile_by_telegram_id(self, telegram_id: int) -> dict[str, Any] | None:
        url = f"{self.backend_url}api/v1/persons/tg/{telegram_id}/"
        status_code, profile_data = await self._api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200 and profile_data:
            return profile_data

        logger.info(f"Failed to retrieve profile for telegram_id {telegram_id}. HTTP status: {status_code}")
        return None

    async def delete_profile(self, profile_id: int, token: str | None = None) -> bool:
        url = f"{self.backend_url}api/v1/persons/{profile_id}/delete/"
        headers = {"Authorization": f"Token {token}"} if token else {}
        status_code, _ = await self._api_request("delete", url, headers=headers)
        return status_code == 204

    async def edit_profile(self, profile_id: int, data: dict, token: str | None = None) -> bool:
        fields = [
            "current_tg_id",
            "language",
            "name",
            "gender",
            "born_in",
            "workout_experience",
            "work_experience",
            "additional_info",
            "payment_details",
            "profile_photo",
            "workout_goals",
            "health_notes",
            "weight",
            "verified",
            "assigned_to",
        ]
        if "payment_details" in data:
            data["payment_details"] = self.encrypter.encrypt(data["payment_details"])
        filtered_data = {key: data[key] for key in fields if key in data and data[key] is not None}
        url = f"{self.backend_url}api/v1/persons/{profile_id}/"
        status_code, _ = await self._api_request("put", url, filtered_data, headers={"Authorization": f"Token {token}"})
        return status_code == 200

    async def reset_telegram_id(self, profile_id: int, telegram_id: int) -> bool:
        url = f"{self.backend_url}api/v1/persons/reset-tg/{profile_id}/"
        data = {"telegram_id": telegram_id}
        status_code, _ = await self._api_request(
            "post", url, data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        return status_code == 200


profile_service = ProfileService(enc)
