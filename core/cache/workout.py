import json
from typing import Any
from dateutil.parser import parse
from loguru import logger

from core.models import Subscription, Program
from base import BaseCacheManager


class WorkoutCacheManager(BaseCacheManager):
    @classmethod
    def update_subscription(cls, profile_id: int, subscription_data: dict) -> None:
        allowed_fields = [
            "payment_date",
            "enabled",
            "price",
            "client_profile",
            "workout_type",
            "workout_days",
            "exercises",
            "wishes",
        ]
        cls.update_json_fields("workout_plans:subscriptions", str(profile_id), subscription_data, allowed_fields)

    @classmethod
    def update_program(cls, profile_id: int, program_data: dict[str, Any]) -> None:
        allowed_fields = [
            "exercises_by_day",
            "split_number",
            "workout_type",
            "wishes",
        ]
        cls.update_json_fields("workout_plans:programs", str(profile_id), program_data, allowed_fields)

    @classmethod
    def save_subscription(cls, profile_id: int, subscription_data: dict) -> None:
        try:
            cls.set("workout_plans:subscriptions", str(profile_id), json.dumps(subscription_data))
            cls.reset_payment_status(profile_id, "subscription")
            logger.debug(f"Subscription for profile_id {profile_id} saved in cache")
        except Exception as e:
            logger.error(f"Failed to save subscription in cache for profile {profile_id}: {e}")

    @classmethod
    def get_subscription(cls, profile_id: int) -> Subscription | None:
        raw = cls.get("workout_plans:subscriptions", str(profile_id))
        if not raw:
            logger.debug(f"No subscription data found for profile_id {profile_id}")
            return None
        try:
            data = json.loads(raw)
            if payment_date := data.get("payment_date"):
                payment_date = parse(payment_date)
                data["payment_date"] = payment_date.strftime("%Y-%m-%d")
            return Subscription.from_dict(data)
        except Exception as e:
            logger.info(f"Failed to get subscription for profile_id {profile_id}: {e}")
            return None

    @classmethod
    def save_program(cls, client_id: int, program_data: dict) -> None:
        try:
            cls.set("workout_plans:programs", str(client_id), json.dumps(program_data))
            logger.debug(f"Program for client {client_id} saved in cache")
        except Exception as e:
            logger.error(f"Failed to save program in cache for client {client_id}: {e}")

    @classmethod
    def get_program(cls, profile_id: int) -> Program | None:
        raw = cls.get("workout_plans:programs", str(profile_id))
        if not raw:
            logger.debug(f"No program data found for profile_id {profile_id}")
            return None
        try:
            data = json.loads(raw)
            data["profile"] = profile_id
            return Program.from_dict(data)
        except Exception as e:
            logger.info(f"Failed to get program for profile_id {profile_id}: {e}")
            return None

    @classmethod
    def set_payment_status(cls, profile_id: int, paid: bool, service_type: str) -> None:
        try:
            cls.set(f"workout_plans:payments:{service_type}", str(profile_id), json.dumps({"paid": paid}))
            logger.debug(f"Program status for profile_id {profile_id} set to {paid}")
        except Exception as e:
            logger.error(f"Failed to set payment status for profile_id {profile_id}: {e}")

    @classmethod
    def reset_payment_status(cls, profile_id: int, service_type: str) -> None:
        try:
            cls.delete(f"workout_plans:payments:{service_type}", str(profile_id))
            logger.debug(f"Payment status for profile_id {profile_id} has been reset")
        except Exception as e:
            logger.error(f"Failed to reset payment status for profile_id {profile_id}: {e}")

    @classmethod
    def check_payment_status(cls, profile_id: int, service_type: str) -> bool:
        raw = cls.get(f"workout_plans:payments:{service_type}", str(profile_id))
        if not raw:
            logger.debug(f"No payment data found for profile_id {profile_id}")
            return False
        try:
            return json.loads(raw).get("paid", False)
        except Exception as e:
            logger.info(f"Failed to check payment status for profile_id {profile_id}: {e}")
            return False

    @classmethod
    def cache_gif_filename(cls, exercise_name: str, filename: str) -> None:
        if not exercise_name or not filename:
            return
        try:
            cls.set("gifs", exercise_name, filename)
        except Exception as e:
            logger.info(f"Failed to cache gif filename for exercise {exercise_name}: {e}")

    @classmethod
    def get_exercise_gif(cls, exercise_name: str) -> str | None:
        try:
            return cls.get("gifs", exercise_name)
        except Exception as e:
            logger.info(f"Failed to get gif filename for exercise {exercise_name}: {e}")
            return None
