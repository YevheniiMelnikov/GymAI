from urllib.parse import urljoin
from loguru import logger

from core.models import Profile
from core.encryptor import Encryptor
from core.services.api_client import APIClient


class ProfileService(APIClient):
    encrypter = Encryptor

    @classmethod
    async def get_profile(cls, profile_id: int) -> Profile | None:
        url = urljoin(cls.api_url, f"api/v1/profiles/{profile_id}/")
        status_code, user_data = await cls._api_request(
            "get",
            url,
            headers={"Authorization": f"Api-Key {cls.api_key}"},
        )
        if status_code == 200 and user_data:
            return Profile.model_validate(user_data)
        logger.info(f"Failed to retrieve profile for id={profile_id}. HTTP status: {status_code}")
        return None

    @classmethod
    async def get_profile_by_tg_id(cls, telegram_id: int) -> Profile | None:
        url = urljoin(cls.api_url, f"api/v1/profiles/tg/{telegram_id}/")
        status_code, profile_data = await cls._api_request(
            "get",
            url,
            headers={"Authorization": f"Api-Key {cls.api_key}"},
        )
        if status_code == 200 and profile_data:
            return Profile.model_validate(profile_data)
        return None

    @classmethod
    async def create_profile(cls, telegram_id: int, status: str, language: str) -> Profile | None:
        url = urljoin(cls.api_url, "api/v1/profiles/")
        data = {
            "tg_id": telegram_id,
            "status": status,
            "language": language,
        }
        status_code, response_data = await cls._api_request(
            "post",
            url,
            data,
            headers={"Authorization": f"Api-Key {cls.api_key}"},
        )
        if status_code == 201 and response_data:
            return Profile.model_validate(response_data)
        logger.error(f"Failed to create profile. status={status_code}, response={response_data}")
        return None

    @classmethod
    async def delete_profile(cls, profile_id: int, token: str | None = None) -> bool:
        url = urljoin(cls.api_url, f"api/v1/profiles/{profile_id}/delete/")
        headers = {"Authorization": f"Token {token}"} if token else {}
        status_code, _ = await cls._api_request("delete", url, headers=headers)
        if status_code != 204:
            logger.error(f"Failed to delete profile {profile_id}. HTTP status: {status_code}")
            return False
        else:
            logger.info(f"Successfully deleted profile {profile_id}")
            return True

    @classmethod
    async def update_profile(cls, profile_id: int, profile_data: dict) -> None:
        url = urljoin(cls.api_url, f"api/v1/profiles/{profile_id}/")
        status_code, _ = await cls._api_request(
            "put",
            url,
            profile_data,
            headers={"Authorization": f"Api-Key {cls.api_key}"},
        )
        if status_code not in {200, 204}:
            logger.error(f"Failed to update profile {profile_id}. HTTP status: {status_code}")

    @classmethod
    async def update_client_profile(cls, profile_id: int, profile_data: dict) -> None:
        url = urljoin(cls.api_url, f"api/v1/client-profiles/{profile_id}/")
        payload = profile_data.copy()
        payload["profile_id"] = profile_id
        status_code, _ = await cls._api_request(
            "put",
            url,
            payload,
            headers={"Authorization": f"Api-Key {cls.api_key}"},
        )
        if status_code not in {200, 204}:
            logger.error(f"Failed to update client profile {profile_id}. HTTP status: {status_code}")

    @classmethod
    async def update_coach_profile(cls, profile_id: int, profile_data: dict) -> None:
        url = urljoin(cls.api_url, f"api/v1/coach-profiles/{profile_id}/")
        payload = profile_data.copy()
        payload["profile_id"] = profile_id
        if "payment_details" in payload:
            payload["payment_details"] = cls.encrypter.encrypt(payload["payment_details"])

        status_code, _ = await cls._api_request(
            "put",
            url,
            payload,
            headers={"Authorization": f"Api-Key {cls.api_key}"},
        )
        if status_code not in {200, 204}:
            logger.error(f"Failed to update coach profile {profile_id}. HTTP status: {status_code}")
