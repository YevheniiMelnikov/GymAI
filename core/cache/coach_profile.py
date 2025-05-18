import json
import random
from loguru import logger

from core.models import Coach
from core.encryptor import Encryptor
from core.exceptions import UserServiceError
from base import BaseCacheManager


class CoachCacheManager(BaseCacheManager):
    encryptor = Encryptor

    @classmethod
    def get_coaches(cls) -> list[Coach] | None:
        try:
            all_coaches = cls.get_all("coaches")
            coaches_data = []
            for k, v in all_coaches.items():
                coach_dict = json.loads(v)
                coach_dict["id"] = int(k)
                coach = Coach.from_dict(coach_dict)
                if coach.verified:
                    coaches_data.append(coach)
            random.shuffle(coaches_data)
            return coaches_data
        except Exception as e:
            logger.info(f"Failed to retrieve coach data: {e}")
            return None

    @classmethod
    def set_coach_data(cls, profile_id: int, profile_data: dict) -> None:
        allowed_fields = [
            "name",
            "surname",
            "work_experience",
            "additional_info",
            "payment_details",
            "profile_photo",
            "verified",
            "assigned_to",
            "subscription_price",
            "program_price",
        ]
        if profile_data.get("payment_details"):
            profile_data["payment_details"] = cls.encryptor.encrypt(profile_data["payment_details"])
        cls.update_json_fields("coaches", str(profile_id), profile_data, allowed_fields)

    @classmethod
    def get_coach(cls, profile_id: int) -> Coach:
        raw = cls.get("coaches", str(profile_id))
        if not raw:
            logger.debug(f"No data found for profile_id {profile_id} in cache")
            raise UserServiceError(
                message="No coach data found", code=404, details=f"Coach ID: {profile_id} not found in Redis cache"
            )
        try:
            data = json.loads(raw)
            data["id"] = profile_id
            if "payment_details" in data:
                data["payment_details"] = cls.encryptor.decrypt(data["payment_details"])
            return Coach.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to get data for profile_id {profile_id} from cache: {e}")
            raise UserServiceError(
                message="Failed to get coach data", code=500, details=f"Error: {e}, Coach ID: {profile_id}"
            )
