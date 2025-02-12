from typing import Any
from urllib.parse import urljoin
import loguru

from services.api_service import APIService
from core.models import Profile
from core.encrypter import encrypter as enc, Encrypter

logger = loguru.logger


class ProfileService(APIService):
    def __init__(self, encrypter: Encrypter):
        super().__init__()
        self.encrypter = encrypter

    async def get_profile(self, profile_id: int) -> dict[str, Any] | None:
        url = urljoin(self.api_url, f"api/v1/profiles/{profile_id}/")
        status_code, user_data = await self._api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200 and user_data:
            return user_data

        logger.info(f"Failed to retrieve email for profile_id {profile_id}. HTTP status: {status_code}")
        return None

    async def get_profile_by_username(self, username: str) -> Profile | None:
        url = urljoin(self.api_url, f"api/v1/profiles/{username}/")
        status_code, profile_data = await self._api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )

        if status_code == 404:
            logger.info(f"Profile for username {username} not found.")
            return None

        if status_code != 200 or not profile_data:
            logger.warning(f"Failed to retrieve profile for {username}. HTTP status: {status_code}")
            return None

        profile_fields = profile_data.get("profile_data", {})
        combined_data = {"id": profile_data.get("id"), "status": profile_fields.get("status"), **profile_fields}

        extra_fields = [
            "surname",
            "additional_info",
            "profile_photo",
            "payment_details",
            "subscription_price",
            "program_price",
            "verified",
            "workout_experience",
            "workout_goals",
            "health_notes",
            "weight",
            "born_in",
        ]

        combined_data.update({field: profile_data.get(field) for field in extra_fields if field in profile_data})
        return Profile.from_dict(combined_data)

    async def get_profile_by_telegram_id(self, telegram_id: int) -> dict[str, Any] | None:
        url = urljoin(self.api_url, f"api/v1/profiles/tg/{telegram_id}/")
        status_code, profile_data = await self._api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 200 and profile_data:
            return profile_data

        return None

    async def delete_profile(self, profile_id: int, token: str | None = None) -> bool:
        url = urljoin(self.api_url, f"api/v1/profiles/{profile_id}/delete/")
        headers = {"Authorization": f"Token {token}"} if token else {}
        status_code, _ = await self._api_request("delete", url, headers=headers)
        return status_code == 204

    async def edit_profile(self, profile_id: int, data: dict) -> bool:
        url = urljoin(self.api_url, f"api/v1/profiles/{profile_id}/")
        fields = ["current_tg_id", "language", "name", "assigned_to"]
        filtered_data = {key: data[key] for key in fields if key in data and data[key] is not None}
        status_code, _ = await self._api_request(
            "put", url, filtered_data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        return status_code == 200

    async def edit_client_profile(self, profile_id: int, data: dict) -> bool:
        url = urljoin(self.api_url, f"api/v1/client-profiles/{profile_id}/")
        fields = ["gender", "born_in", "workout_experience", "workout_goals", "health_notes", "weight", "coach"]
        filtered_data = {key: data[key] for key in fields if key in data and data[key] is not None}
        filtered_data["profile_id"] = profile_id
        status_code, _ = await self._api_request(
            "put", url, filtered_data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        return status_code == 200

    async def edit_coach_profile(self, profile_id: int, data: dict) -> bool:
        fields = [
            "surname",
            "work_experience",
            "additional_info",
            "payment_details",
            "program_price",
            "subscription_price",
            "profile_photo",
            "verified",
        ]
        if "payment_details" in data:
            data["payment_details"] = self.encrypter.encrypt(data["payment_details"])

        filtered_data = {key: data[key] for key in fields if key in data and data[key] is not None}
        filtered_data["profile_id"] = profile_id
        url = urljoin(self.api_url, f"api/v1/coach-profiles/{profile_id}/")
        status_code, _ = await self._api_request(
            "put", url, filtered_data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        return status_code == 200

    async def get_coach_profile(self, profile_id: int) -> dict:
        url = urljoin(self.api_url, f"api/v1/coach-profiles/{profile_id}/")
        status_code, response_data = await self._api_request(
            "get", url, headers={"Authorization": f"Api-Key {self.api_key}"}
        )

        if status_code == 200 and response_data:
            return response_data
        else:
            raise ValueError(f"Failed to get coach profile for profile_id {profile_id}")

    async def reset_telegram_id(self, profile_id: int, telegram_id: int) -> bool:
        url = urljoin(self.api_url, f"api/v1/profiles/reset-tg/{profile_id}/")
        data = {"telegram_id": telegram_id}
        status_code, _ = await self._api_request(
            "post", url, data, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        return status_code == 200


profile_service = ProfileService(enc)
