import json
import random
from typing import Any

from loguru import logger

from core.models import Coach
from core.encryptor import Encryptor
from core.exceptions import UserServiceError
from core.validators import validate_or_raise
from base import BaseCacheManager


class CoachCacheManager(BaseCacheManager):
    encryptor = Encryptor

    @classmethod
    async def get_coaches(cls) -> list[Coach]:
        try:
            all_coaches = await cls.get_all("coaches")
            coaches_data = []
            for k, v in all_coaches.items():
                coach_dict = json.loads(v)
                coach_dict["id"] = int(k)
                coach = validate_or_raise(coach_dict, Coach, context=f"id={k}")
                if coach.verified:
                    coaches_data.append(coach)
            random.shuffle(coaches_data)
            return coaches_data
        except Exception as e:
            logger.warning(f"Failed to retrieve coach data: {e}")
            return []

    @classmethod
    async def update_coach(cls, profile_id: int, profile_data: dict[str, Any]) -> None:
        try:
            if profile_data.get("payment_details"):
                profile_data["payment_details"] = cls.encryptor.encrypt(profile_data["payment_details"])
            await cls.update_json("coaches", str(profile_id), profile_data)
        except Exception as e:
            logger.error(f"Failed to update coach {profile_id}: {e}")

    @classmethod
    async def save_coach(cls, profile_id: int, profile_data: dict[str, Any]) -> None:
        try:
            if profile_data.get("payment_details"):
                profile_data["payment_details"] = cls.encryptor.encrypt(profile_data["payment_details"])
            await cls.set("coaches", str(profile_id), json.dumps(profile_data))
            logger.debug(f"Saved coach data to cache for profile_id={profile_id}")
        except Exception as e:
            logger.error(f"Failed to save coach data for profile_id={profile_id}: {e}")

    @classmethod
    async def get_coach(cls, profile_id: int) -> Coach:
        raw = await cls.get("coaches", str(profile_id))
        if not raw:
            raise UserServiceError(
                message="No coach data found",
                code=404,
                details=f"Coach ID: {profile_id} not found in Redis cache",
            )
        try:
            data = json.loads(raw)
            data["id"] = profile_id
            if "payment_details" in data:
                data["payment_details"] = cls.encryptor.decrypt(data["payment_details"])
            return validate_or_raise(data, Coach, context=f"profile_id={profile_id}")
        except Exception as e:
            raise UserServiceError(
                message="Failed to get coach data", code=500, details=f"Error: {e}, Coach ID: {profile_id}"
            )
