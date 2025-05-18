import json
from typing import Any
from json import JSONDecodeError
from loguru import logger

from core.models import Profile
from core.exceptions import ProfileNotFoundError
from base import BaseCacheManager


class ProfileCacheManager(BaseCacheManager):
    @classmethod
    def get_profile(cls, telegram_id: int) -> Profile | None:
        raw_data = cls.get("user_profiles", str(telegram_id))
        if not raw_data:
            raise ProfileNotFoundError(telegram_id)

        try:
            data = json.loads(raw_data)
            if "id" not in data:
                raise ProfileNotFoundError(telegram_id)
            return Profile.from_dict(data)
        except (JSONDecodeError, TypeError) as e:
            logger.debug(f"Profile data in Redis is invalid or incomplete for user {telegram_id}: {e}")
            raise ProfileNotFoundError(telegram_id)

    @classmethod
    def get_profile_data(cls, telegram_id: int, key_name: str) -> Any:
        profile = cls.get_profile(telegram_id)
        if profile:
            return profile.to_dict().get(key_name)
        return None

    @classmethod
    def set_profile_data(cls, telegram_id: int, data: dict[str, Any]) -> bool:
        allowed_fields = [
            "language",
            "status",
            "tg_id",
        ]
        try:
            filtered_data = {k: data[k] for k in allowed_fields if k in data}
            existing_data = cls.get_json("user_profiles", str(telegram_id)) or {}
            existing_data.update(filtered_data)
            cls.set_json("user_profiles", str(telegram_id), existing_data)
            return True
        except Exception as e:
            logger.error(f"Error setting data for profile_id {telegram_id}: {e}")
            return False

    @classmethod
    def delete_profile(cls, telegram_id: int) -> bool:
        try:
            cls.delete("user_profiles", str(telegram_id))
            logger.info(f"Profile for telegram_id {telegram_id} has been deleted")
            return True
        except Exception as e:
            logger.error(f"Error deleting profile for telegram_id {telegram_id}: {e}")
            return False
