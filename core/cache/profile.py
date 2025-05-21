import json
from json import JSONDecodeError
from loguru import logger

from base import BaseCacheManager
from core.exceptions import ProfileNotFoundError
from core.models import Profile


class ProfileCacheManager(BaseCacheManager):
    @classmethod
    async def save_profile(cls, telegram_id: int, profile_data: dict) -> None:
        try:
            await cls.set("profiles", str(telegram_id), json.dumps(profile_data))
            logger.debug(f"Profile saved for telegram_id={telegram_id}")
        except Exception as e:
            logger.error(f"Failed to save profile for telegram_id={telegram_id}: {e}")

    @classmethod
    async def get_profile(cls, telegram_id: int) -> Profile:
        raw_data = await cls.get("profiles", str(telegram_id))
        if not raw_data:
            raise ProfileNotFoundError(telegram_id)

        try:
            data = json.loads(raw_data)
            if "id" not in data:
                raise ProfileNotFoundError(telegram_id)
            return Profile.model_validate(data)
        except (JSONDecodeError, TypeError, ValueError) as e:
            logger.debug(f"Corrupt profile in cache for telegram_id={telegram_id}: {e}")
            raise ProfileNotFoundError(telegram_id)

    @classmethod
    async def update_profile(cls, telegram_id: int, updates: dict) -> None:
        try:
            current = await cls.get_json("profiles", str(telegram_id)) or {}
            current.update(updates)
            await cls.set_json("profiles", str(telegram_id), current)
            logger.debug(f"Profile updated for telegram_id={telegram_id} with {updates}")
        except Exception as e:
            logger.error(f"Failed to update profile for telegram_id={telegram_id}: {e}")

    @classmethod
    async def delete_profile(cls, telegram_id: int) -> bool:
        try:
            await cls.delete("profiles", str(telegram_id))
            logger.info(f"Profile for telegram_id {telegram_id} has been deleted")
            return True
        except Exception as e:
            logger.error(f"Error deleting profile for telegram_id {telegram_id}: {e}")
            return False
