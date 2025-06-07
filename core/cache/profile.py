import json
from json import JSONDecodeError
from loguru import logger

from base import BaseCacheManager
from core.exceptions import ProfileNotFoundError
from core.schemas import Profile
from core.services import ProfileService


class ProfileCacheManager(BaseCacheManager):
    service = ProfileService

    @classmethod
    async def _deserialize(cls, raw: str, tg_id: int) -> Profile:
        try:
            data = json.loads(raw)
            if "id" not in data:
                raise ValueError("missing id")
            return Profile.model_validate(data)
        except (JSONDecodeError, TypeError, ValueError) as e:
            logger.debug(f"Corrupt profile in cache for tg={tg_id}: {e}")
            raise ProfileNotFoundError(tg_id)

    @classmethod
    async def get_profile(cls, tg_id: int, *, use_fallback: bool = True) -> Profile:
        if raw := await cls.get("profiles", str(tg_id)):
            try:
                return await cls._deserialize(raw, tg_id)
            except ProfileNotFoundError:
                await cls.delete("profiles", str(tg_id))

        if not use_fallback:
            raise ProfileNotFoundError(tg_id)

        profile = await cls.service.get_profile_by_tg_id(tg_id)
        if profile is None:
            raise ProfileNotFoundError(tg_id)

        await cls.set_json("profiles", str(tg_id), profile.model_dump())
        logger.debug(f"Profile pulled from API and cached for tg={tg_id}")
        return profile

    @classmethod
    async def save_profile(cls, tg_id: int, profile_data: dict) -> None:
        try:
            await cls.set("profiles", str(tg_id), json.dumps(profile_data))
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
