from typing import Any
from urllib.parse import urljoin
from common.logger import logger
from core.models import Profile

from services.api_service import APIClient
from core.encryptor import Encryptor


class ProfileService(APIClient):
    encrypter = Encryptor

    @classmethod
    async def get_profile(cls, profile_id: int) -> dict[str, Any] | None:
        url = urljoin(cls.api_url, f"api/v1/profiles/{profile_id}/")
        status_code, user_data = await cls._api_request("get", url, headers={"Authorization": f"Api-Key {cls.api_key}"})
        if status_code == 200 and user_data:
            return user_data

        logger.info(f"Failed to retrieve profile for id={profile_id}. HTTP status: {status_code}")

    @classmethod
    async def get_profile_by_tg_id(cls, telegram_id: int) -> Profile | None:
        url = urljoin(cls.api_url, f"api/v1/profiles/tg/{telegram_id}/")
        status_code, profile_data = await cls._api_request(
            "get", url, headers={"Authorization": f"Api-Key {cls.api_key}"}
        )
        if status_code == 200 and profile_data:
            return Profile.from_dict(profile_data)

    @classmethod
    async def create_profile(cls, telegram_id: int, status: str, language: str) -> Profile | None:
        url = urljoin(cls.api_url, "api/v1/profiles/")
        data = {
            "tg_id": telegram_id,
            "status": status,
            "language": language,
        }

        status_code, response_data = await cls._api_request(
            "post", url, data, headers={"Authorization": f"Api-Key {cls.api_key}"}
        )
        if status_code == 201 and response_data:
            return Profile.from_dict(response_data)

        logger.error(f"Failed to create profile. status={status_code}, response={response_data}")

    @classmethod
    async def delete_profile(cls, profile_id: int, token: str | None = None) -> bool:
        url = urljoin(cls.api_url, f"api/v1/profiles/{profile_id}/delete/")
        headers = {"Authorization": f"Token {token}"} if token else {}
        status_code, _ = await cls._api_request("delete", url, headers=headers)
        return status_code == 204

    @classmethod
    async def edit_profile(cls, profile_id: int, data: dict) -> bool:
        url = urljoin(cls.api_url, f"api/v1/profiles/{profile_id}/")
        fields = ["tg_id", "language", "name", "assigned_to"]
        filtered_data = {k: data[k] for k in fields if k in data and data[k] is not None}
        status_code, _ = await cls._api_request(
            "put", url, filtered_data, headers={"Authorization": f"Api-Key {cls.api_key}"}
        )
        return status_code == 200

    @classmethod
    async def edit_client_profile(cls, profile_id: int, data: dict) -> bool:
        url = urljoin(cls.api_url, f"api/v1/client-profiles/{profile_id}/")
        fields = ["gender", "born_in", "workout_experience", "workout_goals", "health_notes", "weight", "coach"]
        filtered_data = {k: data[k] for k in fields if k in data and data[k] is not None}
        filtered_data["profile_id"] = profile_id
        status_code, _ = await cls._api_request(
            "put", url, filtered_data, headers={"Authorization": f"Api-Key {cls.api_key}"}
        )
        return status_code == 200

    @classmethod
    async def edit_coach_profile(cls, profile_id: int, data: dict) -> bool:
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
            data["payment_details"] = cls.encrypter.encrypt(data["payment_details"])

        filtered_data = {k: data[k] for k in fields if k in data and data[k] is not None}
        filtered_data["profile_id"] = profile_id
        url = urljoin(cls.api_url, f"api/v1/coach-profiles/{profile_id}/")
        status_code, _ = await cls._api_request(
            "put", url, filtered_data, headers={"Authorization": f"Api-Key {cls.api_key}"}
        )
        return status_code == 200

    @classmethod
    async def get_coach_profile(cls, profile_id: int) -> dict:
        url = urljoin(cls.api_url, f"api/v1/coach-profiles/{profile_id}/")
        status_code, response_data = await cls._api_request(
            "get", url, headers={"Authorization": f"Api-Key {cls.api_key}"}
        )
        if status_code == 200 and response_data:
            return response_data
        else:
            raise ValueError(f"Failed to get coach profile for profile_id={profile_id}")
