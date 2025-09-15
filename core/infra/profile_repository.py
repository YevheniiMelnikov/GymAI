from decimal import Decimal
from typing import Any
import httpx
from loguru import logger

from core.encryptor import Encryptor
from core.schemas import Client, Coach, Profile
from core.services.internal.api_client import APIClient, APISettings


class HTTPProfileRepository(APIClient):
    encrypter = Encryptor

    def __init__(self, client: httpx.AsyncClient, settings: APISettings) -> None:
        super().__init__(client, settings)
        self.use_default_auth = False

    @staticmethod
    def _parse_profile(data: dict[str, Any]) -> Profile:
        if hasattr(Profile, "model_validate"):
            return Profile.model_validate(data)
        return Profile(**data)

    async def get_profile(self, profile_id: int) -> Profile | None:
        url = self._build_url(f"api/v1/profiles/{profile_id}/")
        status, data = await self._api_request("get", url, headers={"Authorization": f"Api-Key {self.api_key}"})
        if status == 200 and data:
            return self._parse_profile(data)
        logger.info(f"Profile id={profile_id} not found. HTTP={status}")
        return None

    async def get_profile_by_tg_id(self, tg_id: int) -> Profile | None:
        url = self._build_url(f"api/v1/profiles/tg/{tg_id}/")
        status, data = await self._api_request("get", url, headers={"Authorization": f"Api-Key {self.api_key}"})
        if status == 200 and data:
            return self._parse_profile(data)
        return None

    async def create_profile(self, tg_id: int, role: str, language: str) -> Profile | None:
        url = self._build_url("api/v1/profiles/")
        payload = {"tg_id": tg_id, "role": role, "language": language}
        status_code, data = await self._api_request(
            "post", url, payload, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status_code == 201 and data:
            logger.info(f"Profile created tg_id={tg_id}")
            return self._parse_profile(data)
        logger.error(f"Failed to create profile tg_id={tg_id} url={url}. HTTP={status_code}")
        return None

    async def delete_profile(self, profile_id: int, token: str | None = None) -> bool:
        url = self._build_url(f"api/v1/profiles/{profile_id}/delete/")
        headers = {"Authorization": f"Token {token}"} if token else {}
        status_code, _ = await self._api_request("delete", url, headers=headers)
        if status_code == 204:
            logger.info(f"Successfully deleted profile {profile_id}")
            return True
        if status_code == 404:
            logger.info(f"Profile {profile_id} not found for deletion")
            return False
        logger.error(f"Failed to delete profile {profile_id}. HTTP status: {status_code}")
        return False

    async def update_profile(self, profile_id: int, data: dict[str, Any]) -> bool:
        url = self._build_url(f"api/v1/profiles/{profile_id}/")
        status, _ = await self._api_request("put", url, data, headers={"Authorization": f"Api-Key {self.api_key}"})
        if status in (200, 204):
            logger.info(f"Profile id={profile_id} updated")
            return True
        logger.error(f"Failed to update profile id={profile_id}. HTTP={status}")
        return False

    async def create_client_profile(self, profile_id: int, data: dict[str, Any] | None = None) -> Client | None:
        url = self._build_url("api/v1/client-profiles/")
        payload: dict[str, Any] = {"profile": profile_id}
        if data:
            payload.update(data)
        status, resp = await self._api_request(
            "post", url, payload, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status == 201 and resp:
            logger.info(f"ClientProfile created profile_id={profile_id}")
            return Client.model_validate(resp)
        logger.error(f"Failed to create ClientProfile profile_id={profile_id}. HTTP={status}")
        return None

    async def update_client_profile(self, client_profile_id: int, data: dict[str, Any]) -> bool:
        url = self._build_url(f"api/v1/client-profiles/pk/{client_profile_id}/")
        data = {k: v for k, v in data.items() if k != "profile"}
        status, _ = await self._api_request("patch", url, data, headers={"Authorization": f"Api-Key {self.api_key}"})
        if status in (200, 204):
            logger.info(f"ClientProfile {client_profile_id} updated")
            return True
        logger.error(f"Failed to update ClientProfile {client_profile_id}. HTTP={status}")
        return False

    async def adjust_client_credits(self, profile_id: int, delta: int | Decimal) -> bool:
        client = await self.get_client_by_profile_id(profile_id)
        if client is None:
            logger.error(f"ClientProfile not found for profile_id={profile_id}")
            return False

        int_delta = int(delta)
        new_credits = max(0, int(client.credits) + int_delta)
        return await self.update_client_profile(client.id, {"credits": int(new_credits)})

    async def adjust_coach_payout_due(self, profile_id: int, delta: Decimal) -> bool:
        coach = await self.get_coach_by_profile_id(profile_id)
        if coach is None:
            logger.error(f"CoachProfile not found for profile_id={profile_id}")
            return False

        new_due = (coach.payout_due or Decimal("0")) + delta
        return await self.update_coach_profile(coach.id, {"payout_due": str(new_due)})

    async def create_coach_profile(self, profile_id: int, data: dict[str, Any] | None = None) -> Coach | None:
        url = self._build_url("api/v1/coach-profiles/")
        payload: dict[str, Any] = {"profile": profile_id}
        if data:
            data.pop("profile", None)
            for k, v in data.items():
                payload[k] = str(v) if isinstance(v, Decimal) else v

        if payload.get("payment_details"):
            payload["payment_details"] = self.encrypter.encrypt(payload["payment_details"])

        status, resp = await self._api_request(
            "post", url, payload, headers={"Authorization": f"Api-Key {self.api_key}"}
        )
        if status == 201 and resp:
            logger.info(f"Created coach profile for profile_id={profile_id}")
            return Coach.model_validate(resp)

        logger.error(f"Failed to create CoachProfile profile_id={profile_id}. HTTP={status}")
        return None

    async def update_coach_profile(self, coach_id: int, data: dict[str, Any]) -> bool:
        url = self._build_url(f"api/v1/coach-profiles/pk/{coach_id}/")

        for price_field in ("program_price", "subscription_price"):
            if price_field in data and isinstance(data[price_field], Decimal):
                data[price_field] = str(data[price_field])

        if "payment_details" in data and data["payment_details"]:
            data["payment_details"] = self.encrypter.encrypt(data["payment_details"])
        status, _ = await self._api_request("patch", url, data, headers={"Authorization": f"Api-Key {self.api_key}"})
        if status in (200, 204):
            logger.info(f"CoachProfile {coach_id} updated")
            return True
        logger.error(f"Failed to update CoachProfile {coach_id}. HTTP={status}")
        return False

    async def _get_by_profile(self, tail: str, model):
        url = self._build_url(tail)
        status, data = await self._api_request("get", url, headers={"Authorization": f"Api-Key {self.api_key}"})
        if status == 200 and data:
            return model.model_validate(data)
        return None

    async def get_client(self, client_id: int) -> Client | None:
        url = self._build_url(f"api/v1/client-profiles/pk/{client_id}/")
        status, data = await self._api_request("get", url, headers={"Authorization": f"Api-Key {self.api_key}"})
        if status == 200 and data:
            return Client.model_validate(data)
        return None

    async def get_client_by_profile_id(self, profile_id: int) -> Client | None:
        return await self._get_by_profile(f"api/v1/client-profiles/by-profile/{profile_id}/", Client)

    async def get_coach_by_profile_id(self, profile_id: int) -> Coach | None:
        return await self._get_by_profile(f"api/v1/coach-profiles/by-profile/{profile_id}/", Coach)

    async def get_client_by_tg_id(self, tg_id: int) -> Client | None:
        profile = await self.get_profile_by_tg_id(tg_id)
        return await self.get_client_by_profile_id(profile.id) if profile else None

    async def get_coach_by_tg_id(self, tg_id: int) -> Coach | None:
        profile = await self.get_profile_by_tg_id(tg_id)
        return await self.get_coach_by_profile_id(profile.id) if profile else None

    async def list_coach_profiles(self) -> list[Coach]:
        url = self._build_url("api/v1/coach-profiles/")
        status, data = await self._api_request(
            "get",
            url,
            headers={"Authorization": f"Api-Key {self.api_key}"},
        )

        if status != 200:
            logger.error(f"Failed to fetch coaches list. HTTP={status}")
            return []

        items: list[dict] = (
            data if isinstance(data, list) else data.get("results", []) if isinstance(data, dict) else []
        )

        return [Coach.model_validate(item) for item in items]
