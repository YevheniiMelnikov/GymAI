import json
import inspect
from typing import Any, cast
from loguru import logger

from core.schemas import Subscription, Program
from .base import BaseCacheManager
from core.utils.validators import validate_or_raise
from core.containers import get_container
from core.exceptions import SubscriptionNotFoundError, ProgramNotFoundError, UserServiceError


class WorkoutCacheManager(BaseCacheManager):
    @classmethod
    async def _fetch_from_service(cls, cache_key: str, field: str, *, use_fallback: bool) -> Subscription | Program:
        profile_id = int(field)
        service = get_container().workout_service()
        if inspect.isawaitable(service):
            service = await service
        if cache_key.endswith("subscriptions"):
            subscription = await service.get_latest_subscription(profile_id)
            if subscription is None:
                raise SubscriptionNotFoundError(profile_id)
            return subscription
        program = await service.get_latest_program(profile_id)
        if program is None:
            raise ProgramNotFoundError(profile_id)
        return program

    @classmethod
    def _validate_data(cls, raw: str, cache_key: str, field: str) -> Subscription | Program:
        data = json.loads(raw)
        if cache_key.endswith("subscriptions"):
            if "profile" not in data:
                data["profile"] = int(field)
            return validate_or_raise(data, Subscription, context=f"profile_id={field}")
        if "profile" not in data:
            data["profile"] = int(field)
        return validate_or_raise(data, Program, context=f"profile_id={field}")

    @classmethod
    async def save_subscription(cls, profile_id: int, subscription_data: dict) -> None:
        try:
            from core.cache import Cache

            await cls.set("workout_plans:subscriptions", str(profile_id), json.dumps(subscription_data))
            await Cache.payment.reset_status(profile_id, "subscription")
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
    async def get_latest_subscription(cls, profile_id: int, *, use_fallback: bool = True) -> Subscription:
        return await cls.get_or_fetch(
            "workout_plans:subscriptions",
            str(profile_id),
            use_fallback=use_fallback,
        )

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
    async def get_latest_program(cls, profile_id: int, *, use_fallback: bool = True) -> Program:
        try:
            return await cls.get_or_fetch(
                "workout_plans:programs",
                str(profile_id),
                use_fallback=use_fallback,
            )
        except UserServiceError:
            if not use_fallback:
                raise
            history = cast(
                list[dict[str, Any]],
                await cls.get_json("workout_plans:programs_history", str(profile_id)) or [],
            )
            if history:
                data: dict[str, Any] = history[0]
                try:
                    program = validate_or_raise(data, Program, context=str(profile_id))
                finally:
                    maybe = cls.delete("workout_plans:programs_history", str(profile_id))
                    if inspect.isawaitable(maybe):
                        await maybe
                return program
            raise

    @classmethod
    async def get_all_subscriptions(cls, profile_id: int) -> list[Subscription]:
        raw = await cls.get_json("workout_plans:subscriptions_history", str(profile_id))
        if raw:
            try:
                return [validate_or_raise(cast(dict, item), Subscription, context=str(profile_id)) for item in raw]
            except Exception as e:
                logger.debug(f"Corrupt subscriptions history for profile_id={profile_id}: {e}")
                await cls.delete("workout_plans:subscriptions_history", str(profile_id))

        service = get_container().workout_service()
        if inspect.isawaitable(service):
            service = await service
        subscriptions = await service.get_all_subscriptions(profile_id)
        await cls.set(
            "workout_plans:subscriptions_history",
            str(profile_id),
            json.dumps([s.model_dump() for s in subscriptions]),
        )
        return subscriptions

    @classmethod
    async def get_all_programs(cls, profile_id: int) -> list[Program]:
        raw = await cls.get_json("workout_plans:programs_history", str(profile_id))
        if raw:
            try:
                return [validate_or_raise(cast(dict, item), Program, context=str(profile_id)) for item in raw]
            except Exception as e:
                logger.debug(f"Corrupt programs history for profile_id={profile_id}: {e}")
                await cls.delete("workout_plans:programs_history", str(profile_id))

        service = get_container().workout_service()
        if inspect.isawaitable(service):
            service = await service
        programs = await service.get_all_programs(profile_id)
        await cls.set(
            "workout_plans:programs_history",
            str(profile_id),
            json.dumps([p.model_dump() for p in programs]),
        )
        return programs

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
