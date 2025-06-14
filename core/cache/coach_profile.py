import json
import random
from typing import Any, cast

from loguru import logger

from core.schemas import Coach
from core.encryptor import Encryptor
from core.exceptions import CoachNotFoundError
from core.validators import validate_or_raise
from .base import BaseCacheManager
from core.services.profile_service import ProfileService


class CoachCacheManager(BaseCacheManager):
    encryptor = Encryptor
    service = ProfileService

    @classmethod
    async def _fetch_from_service(cls, cache_key: str, field: str, *, use_fallback: bool) -> Coach:
        coach = await cls.service.get_coach_by_profile_id(int(field))
        if coach is None:
            raise CoachNotFoundError(int(field))
        return coach

    @classmethod
    def _prepare_for_cache(cls, data: Any, cache_key: str, field: str) -> Any:
        coach = cast(Coach, data)
        data = coach.model_dump()
        if "payment_details" in data and data["payment_details"]:
            data["payment_details"] = cls.encryptor.encrypt(data["payment_details"])
        return cls._json_safe(data)

    @classmethod
    def _validate_data(cls, raw: str, cache_key: str, field: str) -> Coach:
        try:
            data = json.loads(raw)
            if "payment_details" in data and data["payment_details"]:
                data["payment_details"] = cls.encryptor.decrypt(data["payment_details"])
            return validate_or_raise(data, Coach, context=f"profile_id={field}")
        except Exception as e:
            logger.debug(f"Corrupt coach data in cache for profile_id={field}: {e}")
            raise CoachNotFoundError(int(field))

    @classmethod
    async def get_coaches(cls) -> list[Coach]:
        try:
            all_coaches = await cls.get_all("coaches")
            coaches_data = []
            for v in all_coaches.values():
                coach_dict = json.loads(v)
                coach = validate_or_raise(coach_dict, Coach, context=f"id={coach_dict.get('id')}")
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
            existing = await cls.get_json("coaches", str(profile_id))
            if not existing:
                coach = await cls.service.get_coach_by_profile_id(profile_id)
                if coach is None:
                    raise CoachNotFoundError(profile_id)
                existing = coach.model_dump()
            if profile_data.get("payment_details"):
                profile_data["payment_details"] = cls.encryptor.encrypt(profile_data["payment_details"])
            existing.update(profile_data)
            await cls.set_json("coaches", str(profile_id), existing)
        except Exception as e:
            logger.error(f"Failed to update coach profile_id={profile_id}: {e}")

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
        return await cls.get_or_fetch("coaches", str(profile_id), use_fallback=use_fallback)
