from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from decimal import Decimal
from typing import cast

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from bot.keyboards import program_manage_kb, subscription_view_kb, program_view_kb
from bot.states import States
from config.app_settings import settings
from core.cache import Cache
from core.enums import ClientStatus, PaymentStatus, SubscriptionPeriod
from core.schemas import Profile, DayExercises, Subscription
from core.exceptions import (
    ClientNotFoundError,
    SubscriptionNotFoundError,
    ProgramNotFoundError,
    ProfileNotFoundError,
)
from core.services import APIService
from bot.utils.chat import send_message
from bot.utils.menus import show_main_menu, show_subscription_page, show_balance_menu
from bot.utils.text import get_translated_week_day
from bot.utils.bot import del_msg, answer_msg, delete_messages, get_webapp_url
from bot.keyboards import yes_no_kb
from bot.texts import msg_text, btn_text


def _next_payment_date(period: SubscriptionPeriod = SubscriptionPeriod.one_month) -> str:
    today = date.today()
    if period is SubscriptionPeriod.six_months:
        next_date = cast(date, today + relativedelta(months=+6))  # pyrefly: ignore[redundant-cast]
    else:
        next_date = cast(date, today + relativedelta(months=+1))  # pyrefly: ignore[redundant-cast]
    return next_date.strftime("%Y-%m-%d")


async def save_workout_plan(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not callback_query.from_user:
        return

    profile = await Cache.profile.get_profile(callback_query.from_user.id)
    assert profile is not None

    data = await state.get_data()
    completed_days = data.get("completed_days") or data.get("day_index", 0) + 1
    split_number = data.get("split") or 0

    profile_id_str = data.get("client_id")
    if profile_id_str is None:
        logger.error("client_id not found in state for save_workout_plan")
        await callback_query.answer(msg_text("error_generic", profile.language), show_alert=True)
        return

    profile_id = int(profile_id_str)

    raw_exercises = data.get("exercises", [])
    exercises: list[DayExercises] = [
        DayExercises.model_validate(ex) if isinstance(ex, dict) else ex for ex in raw_exercises
    ]

    if not any(day.exercises for day in exercises):
        await answer_msg(callback_query, msg_text("no_exercises_to_save", profile.language))
        return

    if completed_days < split_number:
        await answer_msg(callback_query, msg_text("complete_all_days", profile.language), show_alert=True)
        return

    await callback_query.answer(msg_text("saved", profile.language))

    try:
        client = await Cache.client.get_client(profile_id)
    except ClientNotFoundError:
        logger.error(f"Client {profile_id} not found in save_workout_plan")
        await callback_query.answer(msg_text("unexpected_error", profile.language), show_alert=True)
        return

    client_profile = Profile.model_validate(client.profile_data)
    client_lang = client_profile.language if client_profile else settings.DEFAULT_LANG

    if data.get("subscription"):
        try:
            subscription = await Cache.workout.get_latest_subscription(profile_id)
            serialized_exercises = [ex.model_dump() for ex in exercises]

            subscription_data = subscription.model_dump()
            subscription_data.update(
                client_profile=profile_id,
                exercises=serialized_exercises,
            )

            await APIService.workout.update_subscription(subscription.id, subscription_data)
            await Cache.workout.update_subscription(
                profile_id,
                {
                    "exercises": serialized_exercises,
                    "client_profile": profile_id,
                },
            )
            await Cache.payment.reset_status(profile_id, "subscription")

            await send_message(
                recipient=client,
                text=msg_text("program_updated", client_lang),
                bot=bot,
                state=state,
                reply_markup=subscription_view_kb(client_lang),
                include_incoming_message=False,
            )
        except SubscriptionNotFoundError:
            logger.error(f"Subscription not found for client {profile_id} during save_workout_plan, cannot update.")
            await callback_query.answer(msg_text("unexpected_error", profile.language), show_alert=True)
            return
    else:
        try:
            current_program = await Cache.workout.get_latest_program(profile_id)
            wishes = current_program.wishes
            workout_type = getattr(current_program, "workout_type", data.get("workout_type"))
        except ProgramNotFoundError:
            logger.info(f"Original program not found for client {profile_id} when saving new one. Will create new.")
            wishes = ""
            workout_type = data.get("workout_type")

        saved_program = await APIService.workout.save_program(profile_id, exercises, split_number, wishes)

        if saved_program:
            program_data = saved_program.model_dump()
            program_data.update(
                workout_type=workout_type,
                split_number=split_number,
            )
            await Cache.workout.save_program(profile_id, program_data)
            await Cache.payment.reset_status(profile_id, "program")
        else:
            logger.error(f"Failed to save program via API for client {profile_id}")
            await callback_query.answer(msg_text("unexpected_error", profile.language), show_alert=True)
            return

        await send_message(
            recipient=client,
            text=msg_text("new_workout_plan", client_lang),
            bot=bot,
            state=state,
            reply_markup=(
                program_view_kb(client_lang, webapp_url)
                if (webapp_url := get_webapp_url("program", client_lang)) is not None
                else None
            ),
            include_incoming_message=False,
        )

    await Cache.client.update_client(client.profile, {"status": ClientStatus.default})

    message = callback_query.message
    if message and isinstance(message, Message):
        await show_main_menu(message, profile, state)


async def reset_workout_plan(callback_query: CallbackQuery, state: FSMContext) -> None:
    if not callback_query.from_user:
        return

    try:
        profile = await Cache.profile.get_profile(callback_query.from_user.id)
    except ProfileNotFoundError:
        logger.warning(f"Profile not found for user {callback_query.from_user.id} in reset_workout_plan")
        return

    data = await state.get_data()
    profile_id_str = data.get("client_id")
    if profile_id_str is None:
        logger.error("client_id not found in state for reset_workout_plan")
        return

    profile_id = int(profile_id_str)
    split_number = data.get("split", 1)
    client = await Cache.client.get_client(profile_id)
    await callback_query.answer(btn_text("done", profile.language))

    if data.get("subscription"):
        try:
            subscription = await Cache.workout.get_latest_subscription(profile_id)
            subscription_data = subscription.model_dump()
            subscription_data.update(client_profile=profile_id, exercises=[])

            await APIService.workout.update_subscription(subscription.id, subscription_data)
            await Cache.workout.update_subscription(
                profile_id,
                {
                    "exercises": [],
                    "client_profile": profile_id,
                },
            )
            await Cache.client.update_client(client.profile, {"status": ClientStatus.waiting_for_subscription})
            await Cache.payment.set_status(profile_id, "subscription", PaymentStatus.PENDING)
        except SubscriptionNotFoundError:
            logger.error(f"Subscription not found for client {profile_id}, cannot reset")
            return
    else:
        try:
            program = await Cache.workout.get_latest_program(profile_id)
        except ProgramNotFoundError:
            logger.info(f"Program not found for client {profile_id} to reset")
            await answer_msg(callback_query, msg_text("unexpected_error", profile.language))
            return

        await APIService.workout.update_program(program.id, {"exercises_by_day": []})
        await Cache.workout.update_program(profile_id, {"exercises_by_day": []})
        await Cache.client.update_client(client.profile, {"status": ClientStatus.waiting_for_program})

    await state.clear()
    await answer_msg(callback_query, msg_text("enter_daily_program", profile.language).format(day=1))
    await del_msg(callback_query)
    await state.update_data(client_id=profile_id, exercises=[], day_index=0, split=split_number)
    await state.set_state(States.program_manage)


async def next_day_workout_plan(callback_query: CallbackQuery, state: FSMContext) -> None:
    if not callback_query.from_user:
        return

    profile = await Cache.profile.get_profile(callback_query.from_user.id)
    assert profile is not None
    data = await state.get_data()
    completed_days = data.get("day_index", 0)
    split_number = data.get("split") or 0
    exercises = data.get("exercises", [])

    if not any(day.exercises for day in exercises):
        await callback_query.answer(msg_text("no_exercises_to_save", profile.language))
        return

    if completed_days >= split_number:
        await callback_query.answer(msg_text("out_of_range", profile.language))
        return

    await callback_query.answer(btn_text("forward", profile.language))
    await delete_messages(state)
    completed_days += 1

    if data.get("subscription"):
        days = data.get("days", [])
        if completed_days >= len(days):
            await callback_query.answer(msg_text("out_of_range", profile.language))
            return
        week_day = get_translated_week_day(profile.language, days[completed_days]).lower()
    else:
        week_day = completed_days + 1

    message = callback_query.message
    if not message or not isinstance(message, Message):
        return

    exercise_msg = await answer_msg(message, msg_text("enter_exercise", profile.language))
    program_msg = await answer_msg(
        message,
        msg_text("enter_daily_program", profile.language).format(day=week_day),
        reply_markup=program_manage_kb(profile.language, split_number or 1),
    )

    message_ids = [m.message_id for m in [exercise_msg, program_msg] if m]

    await state.update_data(
        day_index=completed_days,
        chat_id=message.chat.id,
        message_ids=message_ids,
    )


async def cache_program_data(data: dict, profile_id: int) -> None:
    program_data = {
        "id": 1,
        "workout_type": data.get("workout_type"),
        "exercises_by_day": [],
        "created_at": datetime.now().timestamp(),
        "client_profile": profile_id,
        "split_number": 1,
        "wishes": data.get("wishes") or "",
    }
    await Cache.workout.save_program(profile_id, program_data)


async def cancel_subscription(profile_id: int, subscription_id: int) -> None:
    await APIService.workout.update_subscription(subscription_id, {"client_profile": profile_id, "enabled": False})
    await Cache.workout.update_subscription(profile_id, {"enabled": False})
    await Cache.payment.reset_status(profile_id, "subscription")


async def process_new_subscription(
    callback_query: CallbackQuery,
    profile: Profile,
    state: FSMContext,
    *,
    confirmed: bool = False,
) -> None:
    language: str = profile.language or settings.DEFAULT_LANG
    await callback_query.answer(msg_text("checkbox_reminding", language), show_alert=True)
    data = await state.get_data()
    client = await Cache.client.get_client(profile.id)
    required = int(data.get("required", 0))
    if client.credits < required:
        await callback_query.answer(msg_text("not_enough_credits", language), show_alert=True)
        await show_balance_menu(callback_query, profile, state)
        return

    service_type = data.get("service_type", "subscription")
    period_map = {
        "subscription_1_month": SubscriptionPeriod.one_month,
        "subscription_6_months": SubscriptionPeriod.six_months,
    }
    period = period_map.get(service_type, SubscriptionPeriod.one_month)

    if not confirmed:
        await state.update_data(required=required, period=period.value)
        await state.set_state(States.confirm_service)
        await answer_msg(
            callback_query,
            msg_text("confirm_service", language).format(balance=client.credits, price=required),
            reply_markup=yes_no_kb(language),
        )
        return

    sub_id = await APIService.workout.create_subscription(
        client_profile_id=client.id,
        workout_days=data.get("workout_days", []),
        wishes=data.get("wishes", ""),
        amount=Decimal(required),
        period=period,
    )
    if sub_id is None:
        await callback_query.answer(msg_text("unexpected_error", language), show_alert=True)
        return

    await APIService.profile.adjust_client_credits(profile.id, -required)
    await Cache.client.update_client(client.profile, {"credits": client.credits - required})
    next_payment = _next_payment_date(period)
    await APIService.workout.update_subscription(sub_id, {"enabled": True, "payment_date": next_payment})
    await Cache.workout.update_subscription(
        client.profile,
        {
            "id": sub_id,
            "enabled": True,
            "payment_date": next_payment,
            "period": period.value,
            "price": required,
        },
    )
    await Cache.payment.reset_status(client.id, "subscription")
    await callback_query.answer(msg_text("payment_success", language), show_alert=True)


async def edit_subscription_days(
    callback_query: CallbackQuery,
    days: list[str],
    profile_id: int,
    state: FSMContext,
    subscription: Subscription,
) -> None:
    subscription_data = subscription.model_dump()
    exercises_data = subscription_data.get("exercises", [])
    exercises = [DayExercises.model_validate(e) for e in exercises_data]
    updated_exercises = {days[i]: [e.model_dump() for e in day.exercises] for i, day in enumerate(exercises)}
    payload = {"workout_days": days, "exercises": updated_exercises, "client_profile": profile_id}
    subscription_data.update(payload)

    await Cache.workout.update_subscription(profile_id, payload)
    await APIService.workout.update_subscription(int(subscription_data["id"]), subscription_data)
    await state.set_state(States.show_subscription)
    await show_subscription_page(callback_query, state, subscription)
    if isinstance(callback_query, CallbackQuery) and isinstance(callback_query.message, Message):
        await del_msg(callback_query.message)
