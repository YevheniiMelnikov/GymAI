from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest
from contextlib import suppress
from typing import cast
from loguru import logger
from uuid import uuid4

from bot.states import States
from bot.texts import MessageText, msg_text
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
from bot.utils.workout_plans import cancel_subscription
from bot.utils.other import generate_order_id
from bot.utils.bot import del_msg, answer_msg, get_webapp_url
from core.exceptions import ProfileNotFoundError, SubscriptionNotFoundError
from core.services import APIService
from bot.keyboards import payment_kb, select_service_kb, select_days_kb, yes_no_kb
from bot.utils.credits import available_packages
from bot.utils.ai_coach import enqueue_workout_plan_generation
from core.enums import WorkoutPlanType, WorkoutType
from core.utils.idempotency import acquire_once

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
        await message.answer(msg_text(MessageText.feedback, profile.language))
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
                msg_text(MessageText.questionnaire_not_completed, profile.language), show_alert=True
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
            msg_text(MessageText.follow_link, profile.language).format(amount=format(pkg.price, "f")),
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
    required = int(data.get("required", 0))
    wishes = data.get("wishes", "")

    if callback_query.data == "no":
        await show_main_menu(cast(Message, callback_query.message), profile, state)
        await del_msg(callback_query)
        return

    request_id = str(uuid4())

    if service == "program":
        if not await acquire_once(f"gen_program:{user_profile.id}", settings.LLM_COOLDOWN):
            logger.warning(
                f"Duplicate program generation suppressed for profile_id={user_profile.id} request_id={request_id}"
            )
            await del_msg(callback_query)
            return

        logger.debug(
            "AI coach plan generation started plan_type=program "
            f"profile_id={user_profile.id} request_id={request_id} ttl={settings.LLM_COOLDOWN}"
        )

    await APIService.profile.adjust_credits(profile.id, -required)
    await Cache.profile.update_record(user_profile.id, {"credits": user_profile.credits - required})
    await answer_msg(callback_query, msg_text(MessageText.request_in_progress, profile.language))
    if isinstance(callback_query.message, Message):
        await show_main_menu(callback_query.message, profile, state)

    if service == "program":
        queued = await enqueue_workout_plan_generation(
            client=user_profile,
            language=profile.language,
            plan_type=WorkoutPlanType.PROGRAM,
            workout_type=WorkoutType(data.get("workout_type", "")),
            wishes=wishes,
            request_id=request_id,
        )
        if not queued:
            await answer_msg(
                callback_query,
                msg_text(MessageText.coach_agent_error, profile.language).format(tg=settings.TG_SUPPORT_CONTACT),
            )
            logger.error(
                f"ai_plan_dispatch_failed plan_type=program profile_id={user_profile.id} request_id={request_id}"
            )
        return

    period_map = {
        "subscription_1_month": SubscriptionPeriod.one_month,
        "subscription_6_months": SubscriptionPeriod.six_months,
    }
    await state.update_data(period=period_map.get(service, SubscriptionPeriod.one_month).value)
    await state.set_state(States.ai_workout_days)
    await answer_msg(
        callback_query,
        msg_text(MessageText.select_days, profile.language),
        reply_markup=select_days_kb(profile.language, []),
    )
    await del_msg(cast(Message | CallbackQuery | None, callback_query))
    return


@menu_router.callback_query(States.ai_workout_days)
async def ai_workout_days(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data.get("profile"))
    lang = profile.language or settings.DEFAULT_LANG
    days: list[str] = data.get("workout_days", [])
    if callback_query.data != "complete":
        data_val = callback_query.data
        if data_val is not None:
            if data_val in days:
                days.remove(data_val)
            else:
                days.append(data_val)
        await state.update_data(workout_days=days)
        message = callback_query.message
        if message and isinstance(message, Message):
            with suppress(TelegramBadRequest):
                await message.edit_reply_markup(reply_markup=select_days_kb(lang, days))
        await state.set_state(States.ai_workout_days)
        return

    if not days:
        await callback_query.answer("❌")
        return

    await state.update_data(workout_days=days)
    selected_profile = Profile.model_validate(data.get("profile"))
    wishes = data.get("wishes", "")
    period = data.get("period", "1m")
    request_id = uuid4().hex
    await answer_msg(callback_query, msg_text(MessageText.request_in_progress, lang))
    await show_main_menu(cast(Message, callback_query.message), profile, state)
    queued = await enqueue_workout_plan_generation(
        client=selected_profile,
        language=lang,
        plan_type=WorkoutPlanType.SUBSCRIPTION,
        workout_type=WorkoutType(data.get("workout_type", "")),
        wishes=wishes,
        request_id=request_id,
        period=period,
        workout_days=days,
    )
    if not queued:
        await answer_msg(
            callback_query,
            msg_text(MessageText.coach_agent_error, lang).format(tg=settings.TG_SUPPORT_CONTACT),
        )
        logger.error(
            f"ai_plan_dispatch_failed plan_type=subscription profile_id={selected_profile.id} request_id={request_id}"
        )
        return
    logger.info(
        f"ai_plan_generation_requested request_id={request_id} profile_id={selected_profile.id} "
        f"plan_type={WorkoutPlanType.SUBSCRIPTION.value}"
    )


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
            msg_text(MessageText.delete_confirmation, profile.language),
            reply_markup=yes_no_kb(profile.language),
        )
        await del_msg(message)
        await state.set_state(States.profile_delete)


@menu_router.message(States.feedback)
async def handle_feedback(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)

    if await process_feedback_content(message, profile, bot):
        logger.info(f"Profile_id {profile.id} sent feedback")
        await message.answer(msg_text(MessageText.feedback_sent, profile.language))
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
        await callback_query.answer(msg_text(MessageText.unexpected_error, profile.language), show_alert=True)
        return

    if cb_data == "back":
        await callback_query.answer()
        await state.set_state(States.select_service)
        await message.answer(
            msg_text(MessageText.select_service, profile.language),
            reply_markup=select_service_kb(profile.language),
        )

    elif cb_data == "change_days":
        await callback_query.answer()
        await state.update_data(edit_mode=True)
        await state.set_state(States.workout_days)
        await message.answer(
            msg_text(MessageText.select_days, profile.language),
            reply_markup=select_days_kb(profile.language, []),
        )

    elif cb_data == "history":
        await show_subscription_history(callback_query, profile, state)

    elif cb_data == "cancel":
        logger.info(f"User {profile.id} requested to stop the subscription")
        await callback_query.answer(msg_text(MessageText.subscription_canceled, profile.language), show_alert=True)

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
            await callback_query.answer(msg_text(MessageText.unexpected_error, profile.language), show_alert=True)
            return

        workout_days = subscription.workout_days
        await state.update_data(
            exercises=subscription.exercises,
            days=workout_days,
            split=len(workout_days),
        )
        await show_exercises_menu(callback_query, state, profile)

    await del_msg(message)
