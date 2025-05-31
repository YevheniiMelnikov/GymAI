from __future__ import annotations

import asyncio
from datetime import datetime
from typing import cast, Optional

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import program_edit_kb, program_manage_kb, program_view_kb, subscription_view_kb, payment_kb
from bot.states import States
from config.env_settings import Settings
from core.cache import Cache
from core.enums import ClientStatus
from core.models import Profile, DayExercises, Subscription
from core.services import APIService
from bot.utils.chat import send_message
from bot.utils.menus import show_main_menu, show_subscription_page
from bot.utils.text import get_translated_week_day
from bot.utils.exercises import format_program
from bot.utils.other import delete_messages, del_msg, answer_msg, generate_order_id
from bot.texts import msg_text, btn_text


async def save_workout_plan(callback_query: CallbackQuery, state: FSMContext) -> None:
    if not callback_query.from_user:
        return

    profile = await Cache.profile.get_profile(callback_query.from_user.id)
    assert profile

    data = await state.get_data()
    completed_days = data.get("completed_days")
    if completed_days is None:
        completed_days = data.get("day_index", 0) + 1

    split_number = data.get("split") or 0
    client_id = cast(Optional[int], data.get("client_id"))
    if client_id is None:
        return

    exercises: list[DayExercises] = data.get("exercises", [])
    has_exercises = any(day.exercises for day in exercises)
    if not has_exercises:
        await answer_msg(callback_query, msg_text("no_exercises_to_save", profile.language))
        return

    if completed_days < split_number:
        await answer_msg(callback_query, msg_text("complete_all_days", profile.language), show_alert=True)
        return

    await callback_query.answer(msg_text("saved", profile.language))

    client = await Cache.client.get_client(client_id)
    client_profile = await APIService.profile.get_profile(client_id)
    client_lang = getattr(client_profile, "language", None) or Settings.DEFAULT_LANG

    if data.get("subscription"):
        subscription = await Cache.workout.get_subscription(client_id)
        if not subscription:
            return
        subscription_data = subscription.model_dump()
        subscription_data.update(client_profile=client_id, exercises=exercises)
        await APIService.workout.update_subscription(cast(int, subscription_data.get("id")), subscription_data)
        await Cache.workout.update_subscription(client_id, dict(exercises=exercises, client_profile=client_id))
        await Cache.workout.reset_payment_status(client_id, "subscription")
        await send_message(
            recipient=client,
            text=msg_text("new_program", client_lang),
            state=state,
            reply_markup=subscription_view_kb(client_lang),
            include_incoming_message=False,
        )
    else:
        program_text = await format_program(exercises, 0)
        current_program = await Cache.workout.get_program(client_id)
        wishes: str = getattr(current_program, "wishes", "") or ""
        program = await APIService.workout.save_program(client_id, exercises, split_number, wishes)
        if program is not None:
            program_data = program.model_dump()
            program_data.update(
                workout_type=getattr(current_program, "workout_type", None),
                split_number=split_number,
            )
            await Cache.workout.save_program(client_id, program_data)
            await Cache.workout.reset_payment_status(client_id, "program")

        await send_message(
            recipient=client,
            text=msg_text("new_program", client_lang),
            state=state,
            include_incoming_message=False,
        )
        await send_message(
            recipient=client,
            text=msg_text("program_page", client_lang).format(program=program_text, day=1),
            state=state,
            reply_markup=program_view_kb(client_lang),
            include_incoming_message=False,
        )

    await Cache.client.update_client(client_id, {"status": ClientStatus.default})
    message = callback_query.message
    if message and isinstance(message, Message):
        await show_main_menu(message, profile, state)


async def reset_workout_plan(callback_query: CallbackQuery, state: FSMContext) -> None:
    if not callback_query.from_user:
        return

    profile = await Cache.profile.get_profile(callback_query.from_user.id)
    assert profile
    data = await state.get_data()
    client_id = cast(Optional[int], data.get("client_id"))
    if client_id is None:
        return

    await callback_query.answer(btn_text("done", profile.language))

    if data.get("subscription"):
        subscription = await Cache.workout.get_subscription(client_id)
        if not subscription:
            return
        subscription_data = subscription.model_dump()
        subscription_data.update(client_profile=client_id, exercises=[])
        await APIService.workout.update_subscription(cast(int, subscription_data.get("id")), subscription_data)
        await Cache.workout.update_subscription(client_id, {"exercises": [], "client_profile": client_id})
        await Cache.client.update_client(client_id, {"status": ClientStatus.waiting_for_subscription})
        await Cache.workout.set_payment_status(client_id, True, "subscription")
    else:
        program = await Cache.workout.get_program(client_id)
        program_id = getattr(program, "id", None)
        if program_id is not None:
            await APIService.workout.update_program(program_id, dict(exercises_by_day=[]))
        await Cache.workout.update_program(client_id, dict(exercises_by_day=[]))
        await Cache.client.update_client(client_id, {"status": ClientStatus.waiting_for_program})
        await Cache.workout.set_payment_status(client_id, True, "program")

    await state.clear()
    message = callback_query.message
    if message and isinstance(message, Message):
        await answer_msg(message, msg_text("enter_daily_program", profile.language).format(day=1))
        await del_msg(message)
    await state.update_data(client_id=client_id, exercises=[], day_index=0)
    await state.set_state(States.program_manage)


async def next_day_workout_plan(callback_query: CallbackQuery, state: FSMContext) -> None:
    if not callback_query.from_user:
        return

    profile = await Cache.profile.get_profile(callback_query.from_user.id)
    assert profile
    data = await state.get_data()
    completed_days = data.get("day_index", 0)
    split_number = data.get("split")
    if split_number is None:
        split_number = 0
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
        if completed_days < len(days):
            week_day = get_translated_week_day(profile.language, days[completed_days]).lower()
        else:
            await callback_query.answer(msg_text("out_of_range", profile.language))
            return
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

    message_ids = []
    if exercise_msg:
        message_ids.append(exercise_msg.message_id)
    if program_msg:
        message_ids.append(program_msg.message_id)

    await state.update_data(
        day_index=completed_days,
        chat_id=message.chat.id,
        message_ids=message_ids,
    )


async def manage_program(callback_query: CallbackQuery, profile: Profile, client_id: str, state: FSMContext) -> None:
    program_paid = await Cache.workout.check_payment_status(int(client_id), "program")
    workout_data = await Cache.workout.get_program(int(client_id))

    if not program_paid and not workout_data:
        await callback_query.answer(msg_text("payment_required", profile.language), show_alert=True)
        await state.set_state(States.show_clients)
        return

    message = callback_query.message
    if not message or not isinstance(message, Message):
        return

    if workout_data and getattr(workout_data, "exercises_by_day", None):
        program = await format_program(getattr(workout_data, "exercises_by_day", []), 0)
        program_msg = await answer_msg(
            message,
            msg_text("program_page", profile.language).format(program=program, day=1),
            reply_markup=program_edit_kb(profile.language),
            disable_web_page_preview=True,
        )

        message_ids = []
        if program_msg:
            message_ids.append(program_msg.message_id)

        await state.update_data(
            chat_id=message.chat.id,
            message_ids=message_ids,
            exercises=getattr(workout_data, "exercises_by_day", []),
            client_id=client_id,
            day_index=0,
        )
        await state.set_state(States.program_edit)
        await del_msg(message)
        return

    no_program_msg = await answer_msg(message, msg_text("no_program", profile.language))
    workouts_number_msg = await answer_msg(message, msg_text("workouts_number", profile.language))

    message_ids = []
    if no_program_msg:
        message_ids.append(no_program_msg.message_id)
    if workouts_number_msg:
        message_ids.append(workouts_number_msg.message_id)

    await state.update_data(
        chat_id=message.chat.id,
        message_ids=message_ids,
        client_id=client_id,
    )
    await state.set_state(States.workouts_number)
    await del_msg(message)


async def cache_program_data(data: dict, profile_id: int) -> None:
    program_data = {
        "id": 1,
        "workout_type": data.get("workout_type"),
        "exercises_by_day": [],
        "created_at": datetime.now().timestamp(),
        "profile": profile_id,
        "split_number": 1,
        "wishes": data.get("wishes") or "",
    }
    await Cache.workout.save_program(profile_id, program_data)


async def cancel_subscription(next_payment_date: datetime, profile_id: int, subscription_id: int) -> None:
    now = datetime.now()
    delay = (next_payment_date - now).total_seconds()
    if delay > 0:
        await asyncio.sleep(delay)
    await APIService.workout.update_subscription(subscription_id, dict(client_profile=profile_id, enabled=False))
    await Cache.workout.save_subscription(profile_id, dict(enabled=False))
    await Cache.workout.reset_payment_status(profile_id, "subscription")


async def process_new_subscription(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    language = cast(str, profile.language or "ua")

    await callback_query.answer(msg_text("checkbox_reminding", language), show_alert=True)

    order_id = generate_order_id()
    client = await Cache.client.get_client(profile.id)
    if not client or not client.assigned_to:
        return
    coach = await Cache.coach.get_coach(client.assigned_to.pop())
    if not coach:
        return

    await state.update_data(order_id=order_id, amount=coach.subscription_price)

    payment_link = await APIService.payment.get_payment_link(
        action="subscribe",
        amount=coach.subscription_price,
        order_id=order_id,
        payment_type="subscription",
        profile_id=profile.id,
    )

    if not isinstance(callback_query.message, Message):
        return

    message = callback_query.message
    if payment_link:
        await state.set_state(States.handle_payment)
        await answer_msg(
            message,
            msg_text("follow_link", language),
            reply_markup=payment_kb(language, payment_link, "subscription"),
        )
    else:
        await answer_msg(message, msg_text("unexpected_error", language))

    await del_msg(message)


async def edit_subscription_days(
    callback_query: CallbackQuery,
    days: list[str],
    profile: Profile,
    state: FSMContext,
    subscription: Subscription,
) -> None:
    subscription_data = subscription.model_dump()
    exercises_data = subscription_data.get("exercises", [])
    exercises = [DayExercises.model_validate(e) for e in exercises_data]
    updated_exercises = {days[i]: [e.model_dump() for e in day.exercises] for i, day in enumerate(exercises)}

    payload = {"workout_days": days, "exercises": updated_exercises, "client_profile": profile.id}
    subscription_data.update(payload)

    await Cache.workout.update_subscription(profile.id, payload)
    await APIService.workout.update_subscription(cast(int, subscription_data["id"]), subscription_data)

    await state.set_state(States.show_subscription)
    await show_subscription_page(callback_query, state, subscription)
    if isinstance(callback_query, CallbackQuery) and isinstance(callback_query.message, Message):
        await del_msg(callback_query.message)
