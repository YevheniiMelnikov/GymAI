from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Awaitable, Callable

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from loguru import logger

from bot.keyboards import plan_updated_kb, program_view_kb
from bot.texts import MessageText, translate
from bot.utils.urls import get_webapp_url
from config.app_settings import settings
from core.ai_coach.state.plan import AiPlanState
from core.cache import Cache
from core.enums import SubscriptionPeriod, WorkoutPlanType
from core.exceptions import SubscriptionNotFoundError
from core.schemas import DayExercises, Profile, Subscription
from core.ai_coach.exercise_catalog import load_exercise_catalog, search_exercises
from core.ai_coach.exercise_catalog.technique_loader import resolve_gif_key_from_canonical_name
from core.services import APIService
from core.utils.billing import next_payment_date


@dataclass(slots=True)
class PlanFinalizeContext:
    """Context for plan finalization strategies."""

    plan_payload_raw: dict[str, Any]
    resolved_profile_id: int
    profile: Profile
    request_id: str
    state: FSMContext
    bot: Bot
    state_tracker: AiPlanState
    notify_failure: Callable[[str], Awaitable[None]]
    action: str
    plan_type: WorkoutPlanType


class PlanFinalizer(ABC):
    """Base strategy for finalizing generated plans."""

    @abstractmethod
    async def finalize(self, context: PlanFinalizeContext) -> None:
        raise NotImplementedError

    async def _apply_fsm_payload(self, context: PlanFinalizeContext, payload: dict[str, object]) -> None:
        await context.state.update_data(**payload)


def _sanitize_exercises_payload(exercises: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for day in exercises:
        day_copy = dict(day)
        raw_exercises = day_copy.get("exercises", [])
        if not isinstance(raw_exercises, list):
            sanitized.append(day_copy)
            continue
        cleaned_exercises: list[dict[str, Any]] = []
        for exercise in raw_exercises:
            if not isinstance(exercise, dict):
                continue
            exercise_copy = dict(exercise)
            if exercise_copy.get("sets_detail") is None:
                exercise_copy.pop("sets_detail", None)
            cleaned_exercises.append(exercise_copy)
        day_copy["exercises"] = cleaned_exercises
        sanitized.append(day_copy)
    return sanitized


def _normalize_exercise_gif_keys(exercises_by_day: list[DayExercises], *, language: str) -> None:
    catalog = load_exercise_catalog()
    catalog_keys = {entry.gif_key for entry in catalog}
    missing = 0
    unknown = 0
    resolved_from_yaml = 0
    resolved_from_search = 0
    missing_samples: list[str] = []
    unknown_samples: list[str] = []
    for day in exercises_by_day:
        for exercise in day.exercises:
            kind = str(getattr(exercise, "kind", "") or "").strip().lower()
            if kind in {"warmup", "cardio"}:
                exercise.gif_key = None
                continue
            gif_key = str(getattr(exercise, "gif_key", "") or "").strip()
            name = str(getattr(exercise, "name", "") or "").strip()
            if gif_key and gif_key not in catalog_keys:
                unknown += 1
                if len(unknown_samples) < 3:
                    unknown_samples.append(gif_key)
                gif_key = ""
                exercise.gif_key = None
            if not gif_key:
                missing += 1
                if len(missing_samples) < 3:
                    missing_samples.append(name)
                resolved = resolve_gif_key_from_canonical_name(name, language)
                if resolved and resolved in catalog_keys:
                    exercise.gif_key = resolved
                    resolved_from_yaml += 1
                    continue
                matches = search_exercises(name_query=name, limit=1) if name else ()
                if matches and matches[0].gif_key in catalog_keys:
                    exercise.gif_key = matches[0].gif_key
                    resolved_from_search += 1
    if missing or unknown:
        logger.warning(
            "program_finalize_gif_keys missing={} unknown={} resolved_yaml={} resolved_search={} "
            "missing_samples={} unknown_samples={}",
            missing,
            unknown,
            resolved_from_yaml,
            resolved_from_search,
            missing_samples,
            unknown_samples,
        )


def _resolve_subscription_period(payload_period: str | None, current_period: str | None) -> str:
    if current_period:
        return str(current_period)
    if payload_period:
        try:
            SubscriptionPeriod(str(payload_period))
            return str(payload_period)
        except ValueError:
            return SubscriptionPeriod.one_month.value
    return SubscriptionPeriod.one_month.value


class ProgramPlanFinalizer(PlanFinalizer):
    """Finalize program plans: persist, cache, update FSM, notify user."""

    @staticmethod
    def _extract_program_exercises(plan_payload_raw: dict[str, Any]) -> list[DayExercises]:
        raw_days = plan_payload_raw.get("exercises_by_day")
        if not isinstance(raw_days, list):
            raw_days = plan_payload_raw.get("exercises")
        if not isinstance(raw_days, list):
            raw_days = []
        return [day if isinstance(day, DayExercises) else DayExercises.model_validate(day) for day in raw_days]

    async def finalize(self, context: PlanFinalizeContext) -> None:
        try:
            exercises_by_day = self._extract_program_exercises(context.plan_payload_raw)
        except Exception as exc:  # noqa: BLE001
            await context.notify_failure(f"day_exercises_validation:{exc!s}")
            logger.error(
                "day_exercises_validation_failed "
                f"profile_id={context.resolved_profile_id} request_id={context.request_id} err={exc}"
            )
            return

        try:
            _normalize_exercise_gif_keys(exercises_by_day, language=str(context.profile.language or ""))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "program_finalize_gif_keys_failed "
                f"profile_id={context.resolved_profile_id} request_id={context.request_id} err={exc!s}"
            )

        split_number = context.plan_payload_raw.get("split_number")
        try:
            split_value = int(split_number) if split_number is not None else len(exercises_by_day)
        except (TypeError, ValueError):
            split_value = len(exercises_by_day)

        wishes_raw = context.plan_payload_raw.get("wishes")
        wishes = str(wishes_raw) if wishes_raw is not None else ""

        saved_program = await APIService.workout.save_program(
            profile_id=context.resolved_profile_id,
            exercises=exercises_by_day,
            split_number=split_value,
            wishes=wishes,
        )
        await Cache.workout.save_program(context.resolved_profile_id, saved_program.model_dump(mode="json"))
        try:
            await APIService.workout.get_latest_program(context.resolved_profile_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                f"warm_program_cache_failed profile_id={context.resolved_profile_id} "
                f"request_id={context.request_id} err={exc!s}"
            )
        exercises_dump = [day.model_dump() for day in saved_program.exercises_by_day]
        split_value = max(1, min(7, split_value))
        await self._apply_fsm_payload(
            context,
            {
                "exercises": exercises_dump,
                "split": split_value,
                "day_index": 0,
            },
        )
        try:
            await context.bot.send_message(
                chat_id=context.profile.tg_id,
                text=translate(MessageText.new_workout_plan, context.profile.language),
                reply_markup=program_view_kb(
                    context.profile.language,
                    get_webapp_url("program", context.profile.language),
                ),
                disable_notification=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ai_plan_program_send_failed "
                f"profile_id={context.resolved_profile_id} request_id={context.request_id} error={exc!s}"
            )
            await context.notify_failure(f"program_send_failed:{exc!s}")
            return

        await context.state_tracker.mark_delivered(context.request_id)
        logger.info(
            "AI coach plan generation finished plan_type=program "
            f"profile_id={context.resolved_profile_id} request_id={context.request_id} program_id={saved_program.id}"
        )


class SubscriptionPlanFinalizer(PlanFinalizer):
    """Finalize subscription plans: persist, cache, update FSM, notify user."""

    async def finalize(self, context: PlanFinalizeContext) -> None:
        subscription = Subscription.model_validate(context.plan_payload_raw)
        serialized_exercises = [day.model_dump() for day in subscription.exercises]

        if context.action == "update":
            await self._finalize_update(context, subscription, serialized_exercises)
            return

        await self._finalize_create(context, subscription, serialized_exercises)

    async def _finalize_update(
        self,
        context: PlanFinalizeContext,
        subscription: Subscription,
        serialized_exercises: list[dict[str, Any]],
    ) -> None:
        state_data = await context.state.get_data()
        subscription_id = state_data.get("subscription_id")
        current_subscription: Subscription | None = None
        if subscription_id is None:
            try:
                current_subscription = await Cache.workout.get_latest_subscription(context.resolved_profile_id)
            except SubscriptionNotFoundError:
                await context.notify_failure("subscription_missing")
                logger.error(
                    "Subscription missing for update "
                    f"profile_id={context.resolved_profile_id} request_id={context.request_id}"
                )
                return
            subscription_id = current_subscription.id
        else:
            try:
                current_subscription = await Cache.workout.get_latest_subscription(context.resolved_profile_id)
                if current_subscription.id != int(subscription_id):
                    logger.warning(
                        "Subscription update id mismatch "
                        f"profile_id={context.resolved_profile_id} request_id={context.request_id} "
                        f"state_id={subscription_id} latest_id={current_subscription.id}"
                    )
            except SubscriptionNotFoundError:
                current_subscription = None

        sanitized_exercises = _sanitize_exercises_payload(serialized_exercises)
        resolved_period = _resolve_subscription_period(
            subscription.period,
            getattr(current_subscription, "period", None) if current_subscription else None,
        )
        subscription_data = {
            "profile": context.resolved_profile_id,
            "exercises": sanitized_exercises,
            "split_number": subscription.split_number,
            "wishes": subscription.wishes,
            "period": resolved_period,
        }
        if current_subscription is not None:
            subscription_data.update(
                {
                    "price": current_subscription.price,
                    "enabled": current_subscription.enabled,
                    "payment_date": current_subscription.payment_date,
                    "workout_location": current_subscription.workout_location,
                }
            )
        await APIService.workout.update_subscription(int(subscription_id), subscription_data)
        await Cache.workout.update_subscription(
            context.resolved_profile_id,
            {
                "exercises": sanitized_exercises,
                "profile": context.resolved_profile_id,
                "split_number": subscription.split_number,
                "wishes": subscription.wishes,
            },
        )
        await self._apply_fsm_payload(
            context,
            {
                "exercises": sanitized_exercises,
                "split": subscription.split_number,
                "day_index": 0,
                "subscription": True,
                "split_number": subscription.split_number,
                **({"last_request_id": context.request_id} if context.request_id else {}),
            },
        )
        try:
            await context.bot.send_message(
                chat_id=context.profile.tg_id,
                text=translate(MessageText.program_updated, context.profile.language),
                parse_mode=ParseMode.HTML,
                reply_markup=plan_updated_kb(
                    context.profile.language,
                    get_webapp_url("subscription", context.profile.language),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ai_plan_subscription_update_notify_failed "
                f"profile_id={context.resolved_profile_id} request_id={context.request_id} error={exc!s}"
            )
            await context.notify_failure(f"subscription_update_send_failed:{exc!s}")
            return
        await context.state_tracker.mark_delivered(context.request_id)
        logger.info(
            "AI coach plan generation finished plan_type=subscription-update "
            f"profile_id={context.resolved_profile_id} "
            f"request_id={context.request_id} subscription_id={subscription_id}"
        )

    async def _finalize_create(
        self,
        context: PlanFinalizeContext,
        subscription: Subscription,
        serialized_exercises: list[dict[str, Any]],
    ) -> None:
        try:
            period_enum = SubscriptionPeriod(subscription.period)
        except ValueError:
            period_enum = SubscriptionPeriod.one_month

        price = Decimal(subscription.price)
        if price <= 0:
            price = Decimal(settings.SMALL_SUBSCRIPTION_PRICE)

        workout_location = subscription.workout_location or context.profile.workout_location or ""
        if not workout_location:
            await context.notify_failure("subscription_missing_workout_location")
            logger.error(
                "Subscription workout_location missing "
                f"profile_id={context.resolved_profile_id} request_id={context.request_id} "
                f"plan_type={context.plan_type.value}"
            )
            return

        subscription_id = await APIService.workout.create_subscription(
            profile_id=context.resolved_profile_id,
            split_number=subscription.split_number,
            wishes=subscription.wishes,
            amount=price,
            period=period_enum,
            workout_location=workout_location,
            exercises=serialized_exercises,
        )
        if subscription_id is None:
            await context.notify_failure("subscription_create_failed")
            logger.error(
                "Subscription create failed "
                f"profile_id={context.resolved_profile_id} request_id={context.request_id} "
                f"plan_type={context.plan_type.value}"
            )
            return

        subscription_dump = subscription.model_dump(mode="json")
        subscription_dump.update(
            id=subscription_id,
            profile=context.resolved_profile_id,
            exercises=serialized_exercises,
        )
        await Cache.workout.save_subscription(context.resolved_profile_id, subscription_dump)
        await self._apply_fsm_payload(
            context,
            {
                "subscription": True,
                "exercises": serialized_exercises,
                "split": subscription.split_number,
                "day_index": 0,
                "split_number": subscription.split_number,
                **({"last_request_id": context.request_id} if context.request_id else {}),
            },
        )
        try:
            await context.bot.send_message(
                chat_id=context.profile.tg_id,
                text=translate(MessageText.subscription_created, context.profile.language).format(
                    bot_name=settings.BOT_NAME
                ),
                reply_markup=program_view_kb(
                    context.profile.language,
                    get_webapp_url("subscription", context.profile.language),
                ),
                disable_notification=True,
            )
            payment_date = next_payment_date(period_enum)
            await APIService.workout.update_subscription(
                subscription_id,
                {"enabled": True, "payment_date": payment_date},
            )
            await Cache.workout.update_subscription(
                context.resolved_profile_id,
                {"enabled": True, "payment_date": payment_date},
            )
            state_data = await context.state.get_data()
            previous_subscription_id = state_data.get("previous_subscription_id")
            if previous_subscription_id and int(previous_subscription_id) != int(subscription_id):
                await APIService.workout.update_subscription(
                    int(previous_subscription_id),
                    {"enabled": False},
                )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ai_plan_subscription_create_notify_failed "
                f"profile_id={context.resolved_profile_id} request_id={context.request_id} error={exc}"
            )
            await context.notify_failure(f"subscription_create_send_failed:{exc!s}")
            return
        await context.state_tracker.mark_delivered(context.request_id)
        logger.info(
            "AI coach plan generation finished plan_type=subscription-create "
            f"profile_id={context.resolved_profile_id} request_id={context.request_id} "
            f"subscription_id={subscription_id}"
        )


FINALIZERS: dict[WorkoutPlanType, PlanFinalizer] = {
    WorkoutPlanType.PROGRAM: ProgramPlanFinalizer(),
    WorkoutPlanType.SUBSCRIPTION: SubscriptionPlanFinalizer(),
}
