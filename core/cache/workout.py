import json
from typing import Any, cast
from inspect import isawaitable
from loguru import logger

from core.schemas import Subscription, Program
from .base import BaseCacheManager
from core.utils.validators import validate_or_raise
from core.containers import get_container
from core.exceptions import SubscriptionNotFoundError, ProgramNotFoundError


class WorkoutCacheManager(BaseCacheManager):
    @classmethod
    async def _fetch_from_service(cls, cache_key: str, field: str, *, use_fallback: bool) -> Subscription | Program:
        client_profile_id = int(field)
        service = get_container().workout_service()
        if isawaitable(service):
            service = await service
        if cache_key.endswith("subscriptions"):
            subscription = await service.get_latest_subscription(client_profile_id)
            if subscription is None:
                raise SubscriptionNotFoundError(client_profile_id)
            return subscription
        program = await service.get_latest_program(client_profile_id)
        if program is None:
            raise ProgramNotFoundError(client_profile_id)
        return program

    @classmethod
    def _validate_data(cls, raw: str, cache_key: str, field: str) -> Subscription | Program:
        data = json.loads(raw)
        if cache_key.endswith("subscriptions"):
            if "client_profile" not in data:
                data["client_profile"] = int(field)
            return validate_or_raise(data, Subscription, context=f"client_profile_id={field}")
        if "client_profile" not in data:
            data["client_profile"] = int(field)
        return validate_or_raise(data, Program, context=f"client_profile_id={field}")

    @classmethod
    async def save_subscription(cls, client_profile_id: int, subscription_data: dict) -> None:
        try:
            from core.cache import Cache

            await cls.set("workout_plans:subscriptions", str(client_profile_id), json.dumps(subscription_data))
            await Cache.payment.reset_status(client_profile_id, "subscription")
            logger.debug(f"Subscription saved for client_profile_id={client_profile_id}")
        except Exception as e:
            logger.error(f"Failed to save subscription for client_profile_id={client_profile_id}: {e}")

    @classmethod
    async def update_subscription(cls, client_profile_id: int, updates: dict) -> None:
        try:
            current = await cls.get_json("workout_plans:subscriptions", str(client_profile_id)) or {}
            current.update(updates)
            await cls.set_json("workout_plans:subscriptions", str(client_profile_id), current)
            logger.debug(f"Subscription updated for client_profile_id={client_profile_id} with {updates}")
        except Exception as e:
            logger.error(f"Failed to update subscription for client_profile_id={client_profile_id}: {e}")

    @classmethod
    async def get_latest_subscription(cls, client_profile_id: int, *, use_fallback: bool = True) -> Subscription:
        return await cls.get_or_fetch(
            "workout_plans:subscriptions",
            str(client_profile_id),
            use_fallback=use_fallback,
        )

    @classmethod
    async def save_program(cls, client_profile_id: int, program_data: dict) -> None:
        try:
            await cls.set("workout_plans:programs", str(client_profile_id), json.dumps(program_data))
            logger.debug(f"Program saved for client_profile_id={client_profile_id}")
        except Exception as e:
            logger.error(f"Failed to save program for client_profile_id={client_profile_id}: {e}")

    @classmethod
    async def update_program(cls, client_profile_id: int, updates: dict[str, Any]) -> None:
        try:
            current = await cls.get_json("workout_plans:programs", str(client_profile_id)) or {}
            current.update(updates)
            await cls.set_json("workout_plans:programs", str(client_profile_id), current)
            logger.debug(f"Program updated for client_profile_id={client_profile_id} with {updates}")
        except Exception as e:
            logger.error(f"Failed to update program for client_profile_id={client_profile_id}: {e}")

    @classmethod
    async def get_latest_program(cls, client_profile_id: int, *, use_fallback: bool = True) -> Program:
        return await cls.get_or_fetch(
            "workout_plans:programs",
            str(client_profile_id),
            use_fallback=use_fallback,
        )

    @classmethod
    async def get_all_subscriptions(cls, client_profile_id: int) -> list[Subscription]:
        raw = await cls.get_json("workout_plans:subscriptions_history", str(client_profile_id))
        if raw:
            try:
                return [
                    validate_or_raise(cast(dict, item), Subscription, context=str(client_profile_id)) for item in raw
                ]
            except Exception as e:
                logger.debug(f"Corrupt subscriptions history for client_profile_id={client_profile_id}: {e}")
                await cls.delete("workout_plans:subscriptions_history", str(client_profile_id))

        service = get_container().workout_service()
        if isawaitable(service):
            service = await service
        subscriptions = await service.get_all_subscriptions(client_profile_id)
        await cls.set(
            "workout_plans:subscriptions_history",
            str(client_profile_id),
            json.dumps([s.model_dump() for s in subscriptions]),
        )
        return subscriptions

    @classmethod
    async def get_all_programs(cls, client_profile_id: int) -> list[Program]:
        raw = await cls.get_json("workout_plans:programs_history", str(client_profile_id))
        if raw:
            try:
                return [validate_or_raise(cast(dict, item), Program, context=str(client_profile_id)) for item in raw]
            except Exception as e:
                logger.debug(f"Corrupt programs history for client_profile_id={client_profile_id}: {e}")
                await cls.delete("workout_plans:programs_history", str(client_profile_id))

        service = get_container().workout_service()
        if isawaitable(service):
            service = await service
        programs = await service.get_all_programs(client_profile_id)
        await cls.set(
            "workout_plans:programs_history",
            str(client_profile_id),
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
