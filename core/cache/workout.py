import json
from typing import Any
from loguru import logger

from core.cache import Cache
from core.schemas import Subscription, Program
from .base import BaseCacheManager
from core.validators import validate_or_raise
from core.services import WorkoutService
from core.exceptions import SubscriptionNotFoundError, ProgramNotFoundError


class WorkoutCacheManager(BaseCacheManager):
    service = WorkoutService

    @classmethod
    async def save_subscription(cls, client_id: int, subscription_data: dict) -> None:
        try:
            await cls.set("workout_plans:subscriptions", str(client_id), json.dumps(subscription_data))
            await Cache.payment.reset_status(client_id, "subscription")
            logger.debug(f"Subscription saved for client_id={client_id}")
        except Exception as e:
            logger.error(f"Failed to save subscription for client_id={client_id}: {e}")

    @classmethod
    async def update_subscription(cls, client_id: int, updates: dict) -> None:
        try:
            current = await cls.get_json("workout_plans:subscriptions", str(client_id)) or {}
            current.update(updates)
            await cls.set_json("workout_plans:subscriptions", str(client_id), current)
            logger.debug(f"Subscription updated for client_id={client_id} with {updates}")
        except Exception as e:
            logger.error(f"Failed to update subscription for client_id={client_id}: {e}")

    @classmethod
    async def get_latest_subscription(cls, client_id: int, *, use_fallback: bool = True) -> Subscription:
        if raw := await cls.get("workout_plans:subscriptions", str(client_id)):
            try:
                data = json.loads(raw)
                if "client_profile" not in data:
                    data["client_profile"] = client_id
                return validate_or_raise(data, Subscription, context=f"client_id={client_id}")
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.debug(f"Corrupt subscription data in cache for client_id={client_id}: {e}")
                await cls.delete("workout_plans:subscriptions", str(client_id))
            except Exception as e:
                logger.error(f"Failed to parse/validate subscription from cache for profile_id={client_id}: {e}")
                await cls.delete("workout_plans:subscriptions", str(client_id))

        if not use_fallback:
            raise SubscriptionNotFoundError(client_id)

        subscription = await cls.service.get_latest_subscription(client_id)
        if subscription is None:
            raise SubscriptionNotFoundError(client_id)

        await cls.set_json("workout_plans:subscriptions", str(client_id), subscription.model_dump())
        logger.debug(f"Subscription for profile_id={client_id} pulled from service and cached")
        return subscription

    @classmethod
    async def save_program(cls, client_id: int, program_data: dict) -> None:
        try:
            await cls.set("workout_plans:programs", str(client_id), json.dumps(program_data))
            logger.debug(f"Program saved for client_id={client_id}")
        except Exception as e:
            logger.error(f"Failed to save program for client_id={client_id}: {e}")

    @classmethod
    async def update_program(cls, client_id: int, updates: dict[str, Any]) -> None:
        try:
            current = await cls.get_json("workout_plans:programs", str(client_id)) or {}
            current.update(updates)
            await cls.set_json("workout_plans:programs", str(client_id), current)
            logger.debug(f"Program updated for client_id={client_id} with {updates}")
        except Exception as e:
            logger.error(f"Failed to update program for client_id={client_id}: {e}")

    @classmethod
    async def get_program(cls, client_id: int, *, use_fallback: bool = True) -> Program:
        if raw := await cls.get("workout_plans:programs", str(client_id)):
            try:
                data = json.loads(raw)
                if "client_id" not in data:
                    data["client_id"] = client_id
                return validate_or_raise(data, Program, context=f"client_id={client_id}")
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.debug(f"Corrupt program data in cache for client_id={client_id}: {e}")
                await cls.delete("workout_plans:programs", str(client_id))
            except Exception as e:
                logger.error(f"Failed to parse/validate program from cache for client_id={client_id}: {e}")
                await cls.delete("workout_plans:programs", str(client_id))

        if not use_fallback:
            raise ProgramNotFoundError(client_id)

        program = await cls.service.get_latest_program(client_id)
        if program is None:
            raise ProgramNotFoundError(client_id)

        await cls.set_json("workout_plans:programs", str(client_id), program.model_dump())
        logger.debug(f"Program for client_id={client_id} pulled from service and cached")
        return program

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
