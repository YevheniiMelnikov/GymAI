from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import uuid4

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from bot.keyboards import diet_confirm_kb
from bot.states import States
from config.app_settings import settings
from core.cache import Cache
from core.enums import SubscriptionPeriod, WorkoutPlanType, WorkoutLocation
from core.exceptions import SubscriptionNotFoundError
from core.schemas import Profile
from core.services import APIService
from core.utils.idempotency import acquire_once
from bot.utils.ai_coach import enqueue_workout_plan_generation
from bot.utils.menus import ensure_credits, show_main_menu
from bot.utils.bot import del_msg, answer_msg
from bot.texts import MessageText, translate
from bot.utils.profiles import resolve_workout_location


async def enqueue_subscription_plan(
    callback_query: CallbackQuery,
    state: FSMContext,
    *,
    period: SubscriptionPeriod,
    workout_days: list[str] | None = None,
) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    selected_profile = Profile.model_validate(profile_data)
    lang = profile.language or settings.DEFAULT_LANG
    wishes = data.get("wishes", "")
    workout_location = resolve_workout_location(selected_profile)
    if workout_location is None:
        logger.error(f"Workout location missing for subscription flow profile_id={selected_profile.id}")
        await callback_query.answer(translate(MessageText.unexpected_error, profile.language), show_alert=True)
        return

    request_id = uuid4().hex
    await answer_msg(callback_query, translate(MessageText.request_in_progress, lang))
    message = callback_query.message
    if message and isinstance(message, Message):
        await show_main_menu(message, profile, state)
    queued = await enqueue_workout_plan_generation(
        profile=selected_profile,
        plan_type=WorkoutPlanType.SUBSCRIPTION,
        workout_location=workout_location,
        wishes=wishes,
        request_id=request_id,
        period=period,
        workout_days=workout_days or [],
    )
    if not queued:
        await answer_msg(
            callback_query,
            translate(MessageText.coach_agent_error, lang).format(tg=settings.TG_SUPPORT_CONTACT),
        )
        logger.error(
            f"ai_plan_dispatch_failed plan_type=subscription profile_id={selected_profile.id} request_id={request_id}"
        )
        return
    logger.info(
        f"ai_plan_generation_requested request_id={request_id} profile_id={selected_profile.id} "
        f"plan_type={WorkoutPlanType.SUBSCRIPTION.value}"
    )


async def cache_program_data(data: dict, profile_id: int, workout_location: str | None = None) -> None:
    program_data = {
        "id": 1,
        "workout_location": workout_location,
        "exercises_by_day": [],
        "created_at": datetime.now().timestamp(),
        "profile": profile_id,
        "split_number": 1,
        "wishes": data.get("wishes") or "",
    }
    await Cache.workout.save_program(profile_id, program_data)


async def process_new_subscription(
    callback_query: CallbackQuery,
    profile: Profile,
    state: FSMContext,
    *,
    confirmed: bool = False,
) -> None:
    language: str = profile.language or settings.DEFAULT_LANG
    data = await state.get_data()
    profile_record = await Cache.profile.get_record(profile.id)
    workout_days = data.get("workout_days", [])
    logger.debug(f"subscription_confirm_flow profile_id={profile.id} workout_days_count={len(workout_days)}")
    required = int(data.get("required", 0))
    if not await ensure_credits(
        callback_query,
        profile,
        state,
        required=required,
        credits=profile_record.credits,
    ):
        return

    workout_location = resolve_workout_location(profile_record)
    if workout_location is None:
        await callback_query.answer(translate(MessageText.unexpected_error, language), show_alert=True)
        return

    try:
        existing = await Cache.workout.get_latest_subscription(profile_record.id)
    except SubscriptionNotFoundError:
        existing = None
    if existing and existing.enabled:
        exercises = existing.exercises or []
        if not exercises:
            existing_id = getattr(existing, "id", None)
            if not existing_id:
                await callback_query.answer(translate(MessageText.unexpected_error, language), show_alert=True)
                await show_main_menu(cast(Message, callback_query.message), profile, state)
                await del_msg(callback_query)
                return
            await APIService.workout.update_subscription(existing_id, {"enabled": False})
            await Cache.workout.update_subscription(profile_record.id, {"enabled": False})
        else:
            await callback_query.answer(translate(MessageText.subscription_already_active, language), show_alert=True)
            await show_main_menu(cast(Message, callback_query.message), profile, state)
            await del_msg(callback_query)
            return

    service_type = data.get("service_type", "subscription")
    period_map = {
        "subscription_1_month": SubscriptionPeriod.one_month,
        "subscription_6_months": SubscriptionPeriod.six_months,
        "subscription_12_months": SubscriptionPeriod.twelve_months,
    }
    period_value = data.get("workout_days_period")
    period: SubscriptionPeriod
    if period_value:
        try:
            period = SubscriptionPeriod(str(period_value))
        except ValueError:
            period = period_map.get(str(data.get("ai_service") or service_type), SubscriptionPeriod.one_month)
    else:
        period = period_map.get(str(data.get("ai_service") or service_type), SubscriptionPeriod.one_month)

    if not confirmed:
        await state.update_data(required=required, period=period.value)
        await state.set_state(States.confirm_service)
        await answer_msg(
            callback_query,
            translate(MessageText.confirm_service, language).format(balance=profile_record.credits, price=required),
            reply_markup=diet_confirm_kb(language),
        )
        return

    if not await acquire_once(f"gen_subscription:{profile_record.id}", settings.LLM_COOLDOWN):
        logger.warning(f"Duplicate subscription generation suppressed for profile_id={profile_record.id}")
        await del_msg(callback_query)
        return

    sub_id = await APIService.workout.create_subscription(
        profile_id=profile_record.id,
        workout_days=data.get("workout_days", []),
        wishes=data.get("wishes", ""),
        amount=Decimal(required),
        period=period,
        workout_location=workout_location.value,
    )
    if sub_id is None:
        await callback_query.answer(translate(MessageText.unexpected_error, language), show_alert=True)
        return

    await APIService.profile.adjust_credits(profile.id, -required)
    await Cache.profile.update_record(profile_record.id, {"credits": profile_record.credits - required})
    await Cache.workout.update_subscription(
        profile_record.id,
        {
            "id": sub_id,
            "enabled": False,
            "period": period.value,
            "price": required,
            "workout_location": workout_location.value,
            "wishes": data.get("wishes", ""),
        },
    )
    request_id = uuid4().hex
    await answer_msg(callback_query, translate(MessageText.request_in_progress, language))
    message = callback_query.message
    if message and isinstance(message, Message):
        await show_main_menu(message, profile, state)
    queued = await enqueue_workout_plan_generation(
        profile=profile_record,
        plan_type=WorkoutPlanType.SUBSCRIPTION,
        workout_location=workout_location,
        wishes=data.get("wishes", ""),
        request_id=request_id,
        period=period.value,
        workout_days=workout_days,
    )
    if not queued:
        await answer_msg(
            callback_query,
            translate(MessageText.coach_agent_error, language).format(tg=settings.TG_SUPPORT_CONTACT),
        )
        logger.error(
            f"ai_plan_dispatch_failed plan_type=subscription profile_id={profile_record.id} request_id={request_id}"
        )
        return
    logger.debug(
        "AI coach plan generation started plan_type=subscription "
        f"profile_id={profile_record.id} request_id={request_id} ttl={settings.LLM_COOLDOWN}"
    )
    logger.info(
        f"ai_plan_generation_requested request_id={request_id} profile_id={profile_record.id} "
        f"plan_type={WorkoutPlanType.SUBSCRIPTION.value}"
    )
    await del_msg(callback_query)


async def process_new_program(
    callback_query: CallbackQuery,
    profile: Profile,
    state: FSMContext,
    *,
    confirmed: bool = False,
) -> None:
    language: str = profile.language or settings.DEFAULT_LANG
    data = await state.get_data()
    profile_record = await Cache.profile.get_record(profile.id)
    workout_days = data.get("workout_days", [])
    logger.debug(f"program_confirm_flow profile_id={profile.id} workout_days_count={len(workout_days)}")
    required = int(data.get("required", 0))
    if not await ensure_credits(
        callback_query,
        profile,
        state,
        required=required,
        credits=profile_record.credits,
    ):
        return

    workout_location_value = data.get("workout_days_location")
    if not workout_location_value:
        logger.error(f"Workout location missing during program flow for profile_id={profile.id}")
        await callback_query.answer(translate(MessageText.unexpected_error, language), show_alert=True)
        return

    if not confirmed:
        await state.update_data(required=required)
        await state.set_state(States.confirm_service)
        await answer_msg(
            callback_query,
            translate(MessageText.confirm_service, language).format(balance=profile_record.credits, price=required),
            reply_markup=diet_confirm_kb(language),
        )
        return

    if not await acquire_once(f"gen_program:{profile_record.id}", settings.LLM_COOLDOWN):
        logger.warning(f"Duplicate program generation suppressed for profile_id={profile_record.id}")
        await del_msg(callback_query)
        return

    await APIService.profile.adjust_credits(profile.id, -required)
    await Cache.profile.update_record(profile.id, {"credits": profile_record.credits - required})
    request_id = uuid4().hex
    await answer_msg(callback_query, translate(MessageText.request_in_progress, language))
    message = callback_query.message
    if message and isinstance(message, Message):
        await show_main_menu(message, profile, state)
    queued = await enqueue_workout_plan_generation(
        profile=profile_record,
        plan_type=WorkoutPlanType.PROGRAM,
        workout_location=WorkoutLocation(workout_location_value),
        wishes=data.get("wishes", ""),
        request_id=request_id,
        workout_days=workout_days,
    )
    if not queued:
        await answer_msg(
            callback_query,
            translate(MessageText.coach_agent_error, language).format(tg=settings.TG_SUPPORT_CONTACT),
        )
        logger.error(
            f"ai_plan_dispatch_failed plan_type=program profile_id={profile_record.id} request_id={request_id}"
        )
        return
    logger.debug(
        "AI coach plan generation started plan_type=program "
        f"profile_id={profile_record.id} request_id={request_id} ttl={settings.LLM_COOLDOWN}"
    )
    logger.info(
        f"ai_plan_generation_requested request_id={request_id} profile_id={profile_record.id} "
        f"plan_type={WorkoutPlanType.PROGRAM.value}"
    )
