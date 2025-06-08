import json
from loguru import logger
from typing import Any

from core.schemas import Client
from core.exceptions import ClientNotFoundError
from .base import BaseCacheManager
from core.validators import validate_or_raise
from core.services.profile_service import ProfileService


class ClientCacheManager(BaseCacheManager):
    service = ProfileService

    @classmethod
    async def update_client(cls, client_id: int, client_data: dict[str, Any]) -> None:
        await cls.update_json("clients", str(client_id), client_data)

    @classmethod
    async def save_client(cls, profile_id: int, client_data: dict[str, Any]) -> None:
        try:
            await cls.set("clients", str(profile_id), json.dumps(client_data))
            logger.debug(f"Saved client data to cache for profile_id={profile_id}")
        except Exception as e:
            logger.error(f"Failed to save client data for profile_id={profile_id}: {e}")

    @classmethod
    async def get_client(cls, profile_id: int, *, use_fallback: bool = True) -> Client:
        if raw := await cls.get("clients", str(profile_id)):
            try:
                data = json.loads(raw)
                data["id"] = profile_id
                return validate_or_raise(data, Client, context=f"profile_id={profile_id}")
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.debug(f"Corrupt client data in cache for profile_id={profile_id}: {e}")
                await cls.delete("clients", str(profile_id))
            except Exception as e:
                logger.error(f"Failed to parse/validate client data from cache for profile_id={profile_id}: {e}")
                await cls.delete("clients", str(profile_id))

        if not use_fallback:
            raise ClientNotFoundError(profile_id)

        client = await cls.service.get_client_by_profile_id(profile_id)
        if client is None:
            raise ClientNotFoundError(profile_id)

        await cls.set_json("clients", str(profile_id), client.model_dump())
        logger.debug(f"Client data for profile_id={profile_id} pulled from service and cached")
        return client
