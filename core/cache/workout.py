import json
from typing import Any, cast
from loguru import logger
from asgiref.sync import sync_to_async
from django.forms.models import model_to_dict

from core.schemas import Subscription, Program
from .base import BaseCacheManager
from core.utils.validators import validate_or_raise
from core.exceptions import UserServiceError, SubscriptionNotFoundError, ProgramNotFoundError
from apps.workout_plans.repos import ProgramRepository, SubscriptionRepository


class WorkoutCacheManager(BaseCacheManager):
    @classmethod
    async def _fetch_from_service(cls, cache_key: str, field: str, *, use_fallback: bool) -> Subscription | Program:
        client_profile_id = int(field)
        if cache_key.endswith("subscriptions"):
            sub_obj = await sync_to_async(SubscriptionRepository.get_latest)(client_profile_id)
            if sub_obj is None:
                raise SubscriptionNotFoundError(client_profile_id)
            sub_dict: dict[str, Any] = model_to_dict(sub_obj)
            sub_dict["client_profile"] = sub_obj.client_profile_id
            sub_dict.setdefault("workout_type", "")
            return validate_or_raise(sub_dict, Subscription, context=str(client_profile_id))

        program_obj = await sync_to_async(ProgramRepository.get_latest)(client_profile_id)
        if program_obj is None:
            raise ProgramNotFoundError(client_profile_id)
        prog_dict: dict[str, Any] = model_to_dict(program_obj)
        prog_dict["client_profile"] = program_obj.client_profile_id
        prog_dict["created_at"] = program_obj.created_at.timestamp()
        return validate_or_raise(prog_dict, Program, context=str(client_profile_id))

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
        try:
            return await cls.get_or_fetch(
                "workout_plans:programs",
                str(client_profile_id),
                use_fallback=use_fallback,
            )
        except UserServiceError:
            if not use_fallback:
                raise
            raw_history = await cls.get_json("workout_plans:programs_history", str(client_profile_id))
            if raw_history:
                try:
                    programs = [
                        validate_or_raise(cast(dict, item), Program, context=str(client_profile_id))
                        for item in raw_history
                    ]
                    programs.sort(key=lambda p: p.created_at, reverse=True)
                    return programs[0]
                except Exception as e:  # pragma: no cover - cache corruption
                    logger.debug(f"Corrupt programs history for client_profile_id={client_profile_id}: {e}")
                    await cls.delete("workout_plans:programs_history", str(client_profile_id))
            raise

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

        subs = await sync_to_async(SubscriptionRepository.get_all)(client_profile_id)
        data = []
        for item in subs:
            item_dict = model_to_dict(item)
            item_dict["client_profile"] = item.client_profile_id
            item_dict.setdefault("workout_type", "")
            data.append(validate_or_raise(item_dict, Subscription, context=str(client_profile_id)))

        await cls.set(
            "workout_plans:subscriptions_history",
            str(client_profile_id),
            json.dumps([d.model_dump() for d in data]),
        )
        return data

    @classmethod
    async def get_all_programs(cls, client_profile_id: int) -> list[Program]:
        raw = await cls.get_json("workout_plans:programs_history", str(client_profile_id))
        if raw:
            try:
                return [validate_or_raise(cast(dict, item), Program, context=str(client_profile_id)) for item in raw]
            except Exception as e:
                logger.debug(f"Corrupt programs history for client_profile_id={client_profile_id}: {e}")
                await cls.delete("workout_plans:programs_history", str(client_profile_id))

        prog_objs = await sync_to_async(ProgramRepository.get_all)(client_profile_id)
        programs: list[Program] = []
        for item in prog_objs:
            item_dict = model_to_dict(item)
            item_dict["client_profile"] = item.client_profile_id
            item_dict["created_at"] = item.created_at.timestamp()
            programs.append(validate_or_raise(item_dict, Program, context=str(client_profile_id)))

        await cls.set(
            "workout_plans:programs_history",
            str(client_profile_id),
            json.dumps([p.model_dump() for p in programs]),
        )
        return programs

    @classmethod
    async def get_program_by_id(cls, client_profile_id: int, program_id: int) -> Program:
        programs = await cls.get_all_programs(client_profile_id)
        for program in programs:
            if program.id == program_id:
                return program
        raise ProgramNotFoundError(client_profile_id)

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
