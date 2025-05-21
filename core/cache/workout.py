import json
from typing import Any
from loguru import logger

from core.models import Subscription, Program
from base import BaseCacheManager
from core.validators import validate_or_raise


class WorkoutCacheManager(BaseCacheManager):
    @classmethod
    async def save_subscription(cls, profile_id: int, subscription_data: dict) -> None:
        try:
            await cls.set("workout_plans:subscriptions", str(profile_id), json.dumps(subscription_data))
            await cls.reset_payment_status(profile_id, "subscription")
            logger.debug(f"Subscription saved for profile_id={profile_id}")
        except Exception as e:
            logger.error(f"Failed to save subscription for profile_id={profile_id}: {e}")

    @classmethod
    async def update_subscription(cls, profile_id: int, updates: dict) -> None:
        try:
            current = await cls.get_json("workout_plans:subscriptions", str(profile_id)) or {}
            current.update(updates)
            await cls.set_json("workout_plans:subscriptions", str(profile_id), current)
            logger.debug(f"Subscription updated for profile_id={profile_id} with {updates}")
        except Exception as e:
            logger.error(f"Failed to update subscription for profile_id={profile_id}: {e}")

    @classmethod
    async def get_subscription(cls, profile_id: int) -> Subscription | None:
        raw = await cls.get("workout_plans:subscriptions", str(profile_id))
        if not raw:
            return None
        try:
            data = json.loads(raw)
            data["client_profile"] = profile_id
            return validate_or_raise(data, Subscription, context=f"profile_id={profile_id}")
        except Exception as e:
            logger.error(f"Failed to parse subscription for profile_id={profile_id}: {e}")
            return None

    @classmethod
    async def save_program(cls, profile_id: int, program_data: dict) -> None:
        try:
            await cls.set("workout_plans:programs", str(profile_id), json.dumps(program_data))
            logger.debug(f"Program saved for profile_id={profile_id}")
        except Exception as e:
            logger.error(f"Failed to save program for profile_id={profile_id}: {e}")

    @classmethod
    async def update_program(cls, profile_id: int, updates: dict[str, Any]) -> None:
        try:
            current = await cls.get_json("workout_plans:programs", str(profile_id)) or {}
            current.update(updates)
            await cls.set_json("workout_plans:programs", str(profile_id), current)
            logger.debug(f"Program updated for profile_id={profile_id} with {updates}")
        except Exception as e:
            logger.error(f"Failed to update program for profile_id={profile_id}: {e}")

    @classmethod
    async def get_program(cls, profile_id: int) -> Program | None:
        raw = await cls.get("workout_plans:programs", str(profile_id))
        if not raw:
            return None
        try:
            data = json.loads(raw)
            data["profile"] = profile_id
            return validate_or_raise(data, Program, context=f"profile_id={profile_id}")
        except Exception as e:
            logger.error(f"Failed to parse program for profile_id={profile_id}: {e}")
            return None

    @classmethod
    async def set_payment_status(cls, profile_id: int, paid: bool, service_type: str) -> None:
        try:
            await cls.set(f"workout_plans:payments:{service_type}", str(profile_id), json.dumps({"paid": paid}))
        except Exception as e:
            logger.error(f"Failed to set payment status for {profile_id}: {e}")

    @classmethod
    async def reset_payment_status(cls, profile_id: int, service_type: str) -> None:
        try:
            await cls.delete(f"workout_plans:payments:{service_type}", str(profile_id))
        except Exception as e:
            logger.error(f"Failed to reset payment status for {profile_id}: {e}")

    @classmethod
    async def check_payment_status(cls, profile_id: int, service_type: str) -> bool:
        raw = await cls.get(f"workout_plans:payments:{service_type}", str(profile_id))
        if not raw:
            return False
        try:
            return json.loads(raw).get("paid", False)
        except Exception as e:
            logger.error(f"Failed to check payment status for {profile_id}: {e}")
            return False

    @classmethod
    async def cache_gif_filename(cls, exercise_name: str, filename: str) -> None:
        try:
            if exercise_name and filename:
                await cls.set("gifs", exercise_name, filename)
        except Exception as e:
            logger.error(f"Failed to cache GIF for {exercise_name}: {e}")

    @classmethod
    async def get_exercise_gif(cls, exercise_name: str) -> str | None:
        try:
            return await cls.get("gifs", exercise_name)
        except Exception as e:
            logger.error(f"Failed to get GIF for {exercise_name}: {e}")
            return None
