from decimal import Decimal
from typing import Any
from urllib.parse import urljoin
from loguru import logger

from core.schemas import Profile, Client, Coach
from core.encryptor import Encryptor
from core.services.api_client import APIClient


class ProfileService(APIClient):
    encrypter = Encryptor

    @classmethod
    async def get_profile(cls, profile_id: int) -> Profile | None:
        url = urljoin(cls.api_url, f"api/v1/profiles/{profile_id}/")
        status, data = await cls._api_request("get", url, headers={"Authorization": f"Api-Key {cls.api_key}"})
        if status == 200 and data:
            return Profile.model_validate(data)
        logger.info(f"Profile id={profile_id} not found. HTTP={status}")
        return None

    @classmethod
    async def get_profile_by_tg_id(cls, tg_id: int) -> Profile | None:
        url = urljoin(cls.api_url, f"api/v1/profiles/tg/{tg_id}/")
        status, data = await cls._api_request("get", url, headers={"Authorization": f"Api-Key {cls.api_key}"})
        if status == 200 and data:
            return Profile.model_validate(data)
        return None

    @classmethod
    async def create_profile(cls, tg_id: int, status: str, language: str) -> Profile | None:
        url = urljoin(cls.api_url, "api/v1/profiles/")
        payload = {"tg_id": tg_id, "status": status, "language": language}
        status_code, data = await cls._api_request(
            "post", url, payload, headers={"Authorization": f"Api-Key {cls.api_key}"}
        )
        if status_code == 201 and data:
            logger.info(f"Profile created tg_id={tg_id}")
            return Profile.model_validate(data)
        logger.error(f"Failed to create profile tg_id={tg_id}. HTTP={status_code}")
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
    async def update_profile(cls, profile_id: int, data: dict[str, Any]) -> bool:
        url = urljoin(cls.api_url, f"api/v1/profiles/{profile_id}/")
        status, _ = await cls._api_request("put", url, data, headers={"Authorization": f"Api-Key {cls.api_key}"})
        if status in (200, 204):
            logger.info(f"Profile id={profile_id} updated")
            return True
        logger.error(f"Failed to update profile id={profile_id}. HTTP={status}")
        return False

    @classmethod
    async def create_client_profile(cls, profile_id: int, data: dict[str, Any] | None = None) -> Client | None:
        url = urljoin(cls.api_url, "api/v1/client-profiles/")
        payload: dict[str, Any] = {"profile": profile_id}
        if data:
            payload.update(data)
        status, resp = await cls._api_request("post", url, payload, headers={"Authorization": f"Api-Key {cls.api_key}"})
        if status == 201 and resp:
            logger.info(f"ClientProfile created profile_id={profile_id}")
            return Client.model_validate(resp)
        logger.error(f"Failed to create ClientProfile profile_id={profile_id}. HTTP={status}")
        return None

    @classmethod
    async def update_client_profile(cls, client_id: int, data: dict[str, Any]) -> bool:
        url = urljoin(cls.api_url, f"api/v1/client-profiles/pk/{client_id}/")
        status, _ = await cls._api_request("patch", url, data, headers={"Authorization": f"Api-Key {cls.api_key}"})
        if status in (200, 204):
            logger.info(f"ClientProfile {client_id} updated")
            return True
        logger.error(f"Failed to update ClientProfile {client_id}. HTTP={status}")
        return False

    @classmethod
    async def create_coach_profile(cls, profile_id: int, data: dict[str, Any] | None = None) -> Coach | None:
        url = urljoin(cls.api_url, "api/v1/coach-profiles/")
        payload: dict[str, Any] = {"profile": profile_id}
        if data:
            data.pop("profile", None)
            for k, v in data.items():
                payload[k] = str(v) if isinstance(v, Decimal) else v

        if payload.get("payment_details"):
            payload["payment_details"] = cls.encrypter.encrypt(payload["payment_details"])

        status, resp = await cls._api_request("post", url, payload, headers={"Authorization": f"Api-Key {cls.api_key}"})
        if status == 201 and resp:
            logger.info(f"Created coach profile for profile_id={profile_id}")
            return Coach.model_validate(resp)

        logger.error(f"Failed to create CoachProfile profile_id={profile_id}. HTTP={status}")
        return None

    @classmethod
    async def update_coach_profile(cls, coach_id: int, data: dict[str, Any]) -> bool:
        url = urljoin(cls.api_url, f"api/v1/coach-profiles/pk/{coach_id}/")

        for price_field in ("program_price", "subscription_price"):
            if price_field in data and isinstance(data[price_field], Decimal):
                data[price_field] = str(data[price_field])

        if "payment_details" in data and data["payment_details"]:
            data["payment_details"] = cls.encrypter.encrypt(data["payment_details"])
        status, _ = await cls._api_request("patch", url, data, headers={"Authorization": f"Api-Key {cls.api_key}"})
        if status in (200, 204):
            logger.info(f"CoachProfile {coach_id} updated")
            return True
        logger.error(f"Failed to update CoachProfile {coach_id}. HTTP={status}")
        return False

    @classmethod
    async def _get_by_profile(cls, tail: str, model):
        url = urljoin(cls.api_url, tail)
        status, data = await cls._api_request("get", url, headers={"Authorization": f"Api-Key {cls.api_key}"})
        if status == 200 and data:
            return model.model_validate(data)
        return None

    @classmethod
    async def get_client_by_profile_id(cls, profile_id: int) -> Client | None:
        return await cls._get_by_profile(f"api/v1/client-profiles/by-profile/{profile_id}/", Client)

    @classmethod
    async def get_coach_by_profile_id(cls, profile_id: int) -> Coach | None:
        return await cls._get_by_profile(f"api/v1/coach-profiles/by-profile/{profile_id}/", Coach)

    @classmethod
    async def get_client_by_tg_id(cls, tg_id: int) -> Client | None:  # TODO: NOT USED YET
        profile = await cls.get_profile_by_tg_id(tg_id)
        return await cls.get_client_by_profile_id(profile.id) if profile else None

    @classmethod
    async def get_coach_by_tg_id(cls, tg_id: int) -> Coach | None:  # TODO: NOT USED YET
        profile = await cls.get_profile_by_tg_id(tg_id)
        return await cls.get_coach_by_profile_id(profile.id) if profile else None
