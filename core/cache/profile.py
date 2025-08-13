import json
from json import JSONDecodeError
from loguru import logger
from pydantic_core._pydantic_core import ValidationError

from .base import BaseCacheManager
from core.exceptions import ProfileNotFoundError
from core.schemas import Profile
from core.containers import get_container


class ProfileCacheManager(BaseCacheManager):
    @classmethod
    async def _fetch_from_service(cls, cache_key: str, field: str, *, use_fallback: bool) -> Profile:
        service = get_container().profile_service()
        profile = await service.get_profile_by_tg_id(int(field))
        if profile is None:
            raise ProfileNotFoundError(int(field))
        return profile

    @classmethod
    def _validate_data(cls, raw: str, cache_key: str, field: str) -> Profile:
        try:
            data = json.loads(raw)
            profile = Profile.model_validate(data)
            return profile
        except (JSONDecodeError, TypeError, ValueError, ValidationError) as e:
            logger.debug(f"Corrupt profile in cache for tg={field}: {e}")
            raise ProfileNotFoundError(int(field))

    @classmethod
    async def get_profile(cls, tg_id: int, *, use_fallback: bool = True) -> Profile:
        return await cls.get_or_fetch("profiles", str(tg_id), use_fallback=use_fallback)

    @classmethod
    async def save_profile(cls, tg_id: int, profile_data: dict) -> None:
        try:
            data = dict(profile_data)
            data["tg_id"] = tg_id
            await cls.set("profiles", str(tg_id), json.dumps(data))
            logger.debug(f"Profile saved for tg_id={tg_id}")
        except Exception as e:
            logger.error(f"Failed to save profile for tg_id={tg_id}: {e}")

    @classmethod
    async def update_profile(cls, tg_id: int, updates: dict) -> None:
        try:
            current = await cls.get_json("profiles", str(tg_id)) or {}
            current.update(updates)
            await cls.set_json("profiles", str(tg_id), current)
            logger.debug(f"Profile updated for tg_id={tg_id} with {updates}")
        except Exception as e:
            logger.error(f"Failed to update profile for tg_id={tg_id}: {e}")

    @classmethod
    async def delete_profile(cls, tg_id: int) -> bool:
        try:
            await cls.delete("profiles", str(tg_id))
            logger.info(f"Profile for tg_id {tg_id} has been deleted")
            return True
        except Exception as e:
            logger.error(f"Error deleting profile for tg_id {tg_id}: {e}")
            return False
