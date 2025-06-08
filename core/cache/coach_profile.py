import json
import random
from typing import Any

from loguru import logger

from core.schemas import Coach
from core.encryptor import Encryptor
from core.exceptions import CoachNotFoundError
from core.validators import validate_or_raise
from .base import BaseCacheManager
from core.services import ProfileService


class CoachCacheManager(BaseCacheManager):
    encryptor = Encryptor
    service = ProfileService

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
    async def update_coach(cls, coach_id: int, profile_data: dict[str, Any]) -> None:
        try:
            if profile_data.get("payment_details"):
                profile_data["payment_details"] = cls.encryptor.encrypt(profile_data["payment_details"])
            await cls.update_json("coaches", str(coach_id), profile_data)
        except Exception as e:
            logger.error(f"Failed to update coach {coach_id}: {e}")

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
    async def get_coach(cls, profile_id: int, *, use_fallback: bool = True) -> Coach:
        if raw := await cls.get("coaches", str(profile_id)):
            try:
                data = json.loads(raw)
                data["id"] = profile_id
                if "payment_details" in data and data["payment_details"]:
                    data["payment_details"] = cls.encryptor.decrypt(data["payment_details"])
                return validate_or_raise(data, Coach, context=f"profile_id={profile_id}")
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.debug(f"Corrupt coach data in cache for profile_id={profile_id}: {e}")
                await cls.delete("coaches", str(profile_id))
            except Exception as e:
                logger.error(f"Failed to parse/validate coach data from cache for profile_id={profile_id}: {e}")
                await cls.delete("coaches", str(profile_id))

        if not use_fallback:
            raise CoachNotFoundError(profile_id)

        coach = await cls.service.get_coach_by_profile_id(profile_id)
        if coach is None:
            raise CoachNotFoundError(profile_id)

        coach_data_to_cache = coach.model_dump()
        if "payment_details" in coach_data_to_cache and coach_data_to_cache["payment_details"]:
            coach_data_to_cache["payment_details"] = cls.encryptor.encrypt(coach_data_to_cache["payment_details"])

        await cls.set_json("coaches", str(profile_id), coach_data_to_cache)
        logger.debug(f"Coach data for profile_id={profile_id} pulled from service and cached")
        return coach
