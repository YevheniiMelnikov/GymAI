import json
from loguru import logger
from typing import Any

from core.schemas import Client
from core.exceptions import ClientNotFoundError
from .base import BaseCacheManager
from core.validators import validate_or_raise
from core.services import ProfileService


class ClientCacheManager(BaseCacheManager):
    service = ProfileService

    @classmethod
    async def _fetch_from_service(cls, cache_key: str, field: str, *, use_fallback: bool) -> Client:
        client = await cls.service.get_client_by_profile_id(int(field))
        if client is None:
            raise ClientNotFoundError(int(field))
        return client

    @classmethod
    def _validate_data(cls, raw: str, cache_key: str, field: str) -> Client:
        try:
            data = json.loads(raw)
            return validate_or_raise(data, Client, context=f"profile_id={field}")
        except Exception as e:
            logger.debug(f"Corrupt client data in cache for profile_id={field}: {e}")
            raise ClientNotFoundError(int(field))

    @classmethod
    async def update_client(cls, profile_id: int, client_data: dict[str, Any]) -> None:
        if "profile" not in client_data:
            client_data["profile"] = profile_id
        await cls.update_json("clients", str(profile_id), client_data)

    @classmethod
    async def save_client(cls, profile_id: int, client_data: dict[str, Any]) -> None:
        try:
            if "profile" not in client_data:
                client_data["profile"] = profile_id
            await cls.set("clients", str(profile_id), json.dumps(client_data))
            logger.debug(f"Saved client data to cache for profile_id={profile_id}")
        except Exception as e:
            logger.error(f"Failed to save client data for profile_id={profile_id}: {e}")

    @classmethod
    async def get_client(cls, profile_id: int, *, use_fallback: bool = True) -> Client:
        return await cls.get_or_fetch("clients", str(profile_id), use_fallback=use_fallback)
