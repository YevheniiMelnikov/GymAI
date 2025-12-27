from datetime import datetime
from uuid import uuid4

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from bot.texts import MessageText, translate
from bot.utils.ai_coach import enqueue_workout_plan_generation
from bot.utils.bot import answer_msg, notify_request_in_progress
from bot.utils.menus import show_main_menu
from bot.flows.plan import ProgramPlanFlow, SubscriptionPlanFlow
from bot.utils.profiles import resolve_workout_location
from config.app_settings import settings
from core.cache import Cache
from core.enums import SubscriptionPeriod, WorkoutPlanType
from core.schemas import Profile


async def enqueue_subscription_plan(
    callback_query: CallbackQuery,
    state: FSMContext,
    *,
    period: SubscriptionPeriod,
    split_number: int | None = None,
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
    await notify_request_in_progress(callback_query, lang)
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
        split_number=split_number or 1,
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
    await SubscriptionPlanFlow(callback_query, profile, state).run(confirmed=confirmed)


async def process_new_program(
    callback_query: CallbackQuery,
    profile: Profile,
    state: FSMContext,
    *,
    confirmed: bool = False,
) -> None:
    await ProgramPlanFlow(callback_query, profile, state).run(confirmed=confirmed)
