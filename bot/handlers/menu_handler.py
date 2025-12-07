from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from typing import cast
from loguru import logger
from uuid import uuid4

from bot.states import States
from bot.texts import MessageText, translate
from config.app_settings import settings
from core.cache import Cache
from core.enums import SubscriptionPeriod
from core.schemas import Profile
from bot.utils.chat import process_feedback_content
from bot.utils.menus import (
    show_main_menu,
    show_exercises_menu,
    show_profile_editing_menu,
    show_my_workouts_menu,
    show_my_profile_menu,
    show_subscription_history,
    show_balance_menu,
    process_ai_service_selection,
)
from bot.utils.workout_plans import cancel_subscription, enqueue_subscription_plan
from bot.utils.other import generate_order_id
from bot.utils.bot import del_msg, answer_msg, get_webapp_url
from core.exceptions import ProfileNotFoundError, SubscriptionNotFoundError
from core.services import APIService
from bot.keyboards import (
    feedback_kb,
    payment_kb,
    select_service_kb,
    yes_no_kb,
)
from bot.utils.credits import available_packages
from bot.utils.ai_coach import enqueue_workout_plan_generation
from bot.utils.profiles import resolve_workout_location
from core.enums import WorkoutLocation, WorkoutPlanType
from core.utils.idempotency import acquire_once
from bot.utils.workout_days import (
    WORKOUT_DAYS_BACK,
    WORKOUT_DAYS_CONTINUE,
    WORKOUT_DAYS_MINUS,
    WORKOUT_DAYS_PLUS,
    DEFAULT_WORKOUT_DAYS_COUNT,
    day_labels,
    start_workout_days_selection,
    update_workout_days_message,
)

menu_router = Router()


@menu_router.callback_query(States.main_menu)
async def main_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    message = callback_query.message
    if message is None or not isinstance(message, Message):
        return
    cb_data = callback_query.data or ""

    if cb_data == "feedback":
        await callback_query.answer()
        await message.answer(
            translate(MessageText.feedback, profile.language),
            reply_markup=feedback_kb(profile.language),
        )
        await state.set_state(States.feedback)
        await del_msg(message)

    elif cb_data == "my_profile":
        await show_my_profile_menu(callback_query, profile, state)

    elif cb_data == "my_workouts":
        await show_my_workouts_menu(callback_query, profile, state)


@menu_router.callback_query(States.choose_plan)
async def plan_choice(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data.get("profile"))
    cb_data = callback_query.data or ""

    if cb_data == "back":
        await show_my_profile_menu(callback_query, profile, state)
        return

    if cb_data.startswith("plan_"):
        plan_name = cb_data.split("_", 1)[1]
        packages = {p.name: p for p in available_packages()}
        pkg = packages.get(plan_name)
        if not pkg:
            await callback_query.answer()
            return

        try:
            user_profile: Profile = await Cache.profile.get_record(profile.id)
        except ProfileNotFoundError:
            await callback_query.answer(
                translate(MessageText.questionnaire_not_completed, profile.language), show_alert=True
            )
            await del_msg(callback_query)
            return

        order_id = generate_order_id()
        await APIService.payment.create_payment(user_profile.id, "credits", order_id, pkg.price)
        webapp_url = get_webapp_url(
            "payment",
            profile.language,
            {"order_id": order_id, "payment_type": "credits"},
        )
        link: str | None = None
        if webapp_url is None:
            logger.warning("WEBAPP_PUBLIC_URL is missing, falling back to LiqPay link for payment")
            link = await APIService.payment.get_payment_link(
                "pay",
                pkg.price,
                order_id,
                "credits",
                user_profile.id,
            )
        await state.update_data(order_id=order_id, amount=str(pkg.price), service_type="credits")
        await state.set_state(States.handle_payment)
        await answer_msg(
            callback_query,
            translate(MessageText.follow_link, profile.language).format(amount=format(pkg.price, "f")),
            reply_markup=payment_kb(profile.language, "credits", webapp_url=webapp_url, link=link),
        )
    await del_msg(callback_query)


@menu_router.callback_query(States.choose_ai_service)
async def ai_service_choice(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data.get("profile"))
    cb_data = callback_query.data or ""

    if cb_data == "back":
        await show_my_workouts_menu(callback_query, profile, state)
        return

    if cb_data.startswith("ai_service_"):
        handled = await process_ai_service_selection(
            callback_query,
            profile,
            state,
            service_name=cb_data.removeprefix("ai_service_"),
        )
        if handled:
            await del_msg(callback_query)
        return


@menu_router.callback_query(States.ai_confirm_service)
async def ai_confirm_service(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data.get("profile"))
    user_profile = Profile.model_validate(data.get("profile"))
    service = data.get("ai_service", "program")

    if callback_query.data == "no":
        await show_main_menu(cast(Message, callback_query.message), profile, state)
        await del_msg(callback_query)
        return

    lang = profile.language or settings.DEFAULT_LANG

    if service == "program":
        workout_location = resolve_workout_location(user_profile)
        if workout_location is None:
            logger.error(f"Workout location missing for completed profile_id={user_profile.id}")
            await callback_query.answer(translate(MessageText.unexpected_error, profile.language), show_alert=True)
            return
        if not await acquire_once(f"gen_program:{user_profile.id}", settings.LLM_COOLDOWN):
            logger.warning(f"Duplicate program generation suppressed for profile_id={user_profile.id}")
            await del_msg(callback_query)
            return
        await start_workout_days_selection(
            callback_query,
            state,
            lang=lang,
            service=service,
            workout_location=workout_location.value,
        )
        return

    period_map = {
        "subscription_1_month": SubscriptionPeriod.one_month,
        "subscription_6_months": SubscriptionPeriod.six_months,
        "subscription_12_months": SubscriptionPeriod.twelve_months,
    }
    period = period_map.get(service, SubscriptionPeriod.one_month)
    await start_workout_days_selection(
        callback_query,
        state,
        lang=lang,
        service=service,
        period_value=period.value,
    )
    return


@menu_router.callback_query(States.workout_days_selection)
async def workout_days_selection(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    lang = profile.language or settings.DEFAULT_LANG
    count = int(data.get("workout_days_count", DEFAULT_WORKOUT_DAYS_COUNT))
    action = callback_query.data
    if action == WORKOUT_DAYS_PLUS:
        if count >= 7:
            await callback_query.answer(translate(MessageText.out_of_range, lang), show_alert=True)
            return
        count += 1
        await state.update_data(workout_days_count=count)
        await update_workout_days_message(callback_query, lang, count)
        await callback_query.answer()
        return
    if action == WORKOUT_DAYS_MINUS:
        if count <= 1:
            await callback_query.answer(translate(MessageText.out_of_range, lang), show_alert=True)
            return
        count -= 1
        await state.update_data(workout_days_count=count)
        await update_workout_days_message(callback_query, lang, count)
        await callback_query.answer()
        return
    if action == WORKOUT_DAYS_BACK:
        await callback_query.answer()
        message = callback_query.message
        if message and isinstance(message, Message):
            await show_main_menu(message, profile, state)
        return
    if action != WORKOUT_DAYS_CONTINUE:
        await callback_query.answer()
        return
    await callback_query.answer()
    service = data.get("workout_days_service", "program")
    selected_days = day_labels(count)
    required = int(data.get("required", 0))
    wishes = data.get("wishes", "")
    if service == "program":
        workout_location_value = data.get("workout_days_location")
        if not workout_location_value:
            logger.error(f"Workout location missing during program flow for profile_id={profile.id}")
            await callback_query.answer(translate(MessageText.unexpected_error, lang), show_alert=True)
            return
        await APIService.profile.adjust_credits(profile.id, -required)
        await Cache.profile.update_record(profile.id, {"credits": profile.credits - required})
        request_id = str(uuid4())
        await answer_msg(callback_query, translate(MessageText.request_in_progress, lang))
        message = callback_query.message
        if message and isinstance(message, Message):
            await show_main_menu(message, profile, state)
        queued = await enqueue_workout_plan_generation(
            profile=profile,
            plan_type=WorkoutPlanType.PROGRAM,
            workout_location=WorkoutLocation(workout_location_value),
            wishes=wishes,
            request_id=request_id,
            workout_days=selected_days,
        )
        if not queued:
            await answer_msg(
                callback_query,
                translate(MessageText.coach_agent_error, lang).format(tg=settings.TG_SUPPORT_CONTACT),
            )
            logger.error(f"ai_plan_dispatch_failed plan_type=program profile_id={profile.id} request_id={request_id}")
            return
        logger.debug(
            "AI coach plan generation started plan_type=program "
            f"profile_id={profile.id} request_id={request_id} ttl={settings.LLM_COOLDOWN}"
        )
        logger.info(
            f"ai_plan_generation_requested request_id={request_id} profile_id={profile.id} "
            f"plan_type={WorkoutPlanType.PROGRAM.value}"
        )
        return
    period_value = data.get("workout_days_period")
    try:
        period = SubscriptionPeriod(period_value) if period_value else SubscriptionPeriod.one_month
    except ValueError:
        period = SubscriptionPeriod.one_month
    await APIService.profile.adjust_credits(profile.id, -required)
    await Cache.profile.update_record(profile.id, {"credits": profile.credits - required})
    await enqueue_subscription_plan(
        callback_query,
        state,
        period=period,
        workout_days=selected_days,
    )
    return


@menu_router.callback_query(States.profile)
async def profile_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    message = callback_query.message
    if message is None or not isinstance(message, Message):
        return
    cb_data = callback_query.data or ""

    if cb_data == "profile_edit":
        await show_profile_editing_menu(message, profile, state)
    elif cb_data == "balance":
        await show_balance_menu(callback_query, profile, state)
    elif cb_data == "back":
        await show_main_menu(message, profile, state)
    else:
        await message.answer(
            translate(MessageText.delete_confirmation, profile.language),
            reply_markup=yes_no_kb(profile.language),
        )
        await del_msg(message)
        await state.set_state(States.profile_delete)


@menu_router.callback_query(States.feedback)
async def feedback_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    if callback_query.data != "back":
        return

    message = callback_query.message
    if message is None or not isinstance(message, Message):
        await callback_query.answer()
        return

    await callback_query.answer()
    await show_main_menu(message, profile, state)
    await del_msg(callback_query)


@menu_router.message(States.feedback)
async def handle_feedback(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)

    if await process_feedback_content(message, profile, bot):
        logger.info(f"Profile_id {profile.id} sent feedback")
        await message.answer(translate(MessageText.feedback_sent, profile.language))
        await show_main_menu(message, profile, state)


@menu_router.callback_query(States.show_subscription)
async def show_subscription_actions(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    message = callback_query.message
    if message is None or not isinstance(message, Message):
        return
    cb_data = callback_query.data or ""

    try:
        profile_record = await Cache.profile.get_record(profile.id)
    except ProfileNotFoundError:
        logger.warning(f"Profile not found for profile_id {profile.id}")
        await callback_query.answer(translate(MessageText.unexpected_error, profile.language), show_alert=True)
        return

    if cb_data == "back":
        await callback_query.answer()
        await state.set_state(States.select_service)
        await message.answer(
            translate(MessageText.select_service, profile.language).format(bot_name=settings.BOT_NAME),
            reply_markup=select_service_kb(profile.language),
        )

    elif cb_data == "history":
        await show_subscription_history(callback_query, profile, state)

    elif cb_data == "cancel":
        logger.info(f"User {profile.id} requested to stop the subscription")
        await callback_query.answer(translate(MessageText.subscription_canceled, profile.language), show_alert=True)

        if not callback_query.from_user:
            return
        subscription = await Cache.workout.get_latest_subscription(profile_record.id)
        if subscription is None:
            return

        await cancel_subscription(profile_record.id, subscription.id)
        logger.info(f"Subscription for profile_id {profile_record.id} deactivated")
        await show_main_menu(message, profile, state)

    else:
        await callback_query.answer()
        try:
            subscription = await Cache.workout.get_latest_subscription(profile_record.id)
        except SubscriptionNotFoundError:
            logger.warning(f"Subscription not found for profile_id {profile_record.id}")
            await callback_query.answer(translate(MessageText.unexpected_error, profile.language), show_alert=True)
            return

        workout_days = subscription.workout_days
        await state.update_data(
            exercises=subscription.exercises,
            days=workout_days,
            split=len(workout_days),
        )
        await show_exercises_menu(callback_query, state, profile)

    await del_msg(message)
