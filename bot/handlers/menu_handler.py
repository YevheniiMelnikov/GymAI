from __future__ import annotations

from datetime import datetime
from typing import cast

from aiogram import Bot, Router
from aiogram.client.session import aiohttp
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from dateutil.relativedelta import relativedelta
from loguru import logger

from bot.keyboards import (
    select_service_kb,
    choose_coach_kb,
    select_days_kb,
    gift_kb,
    yes_no_kb,
)
from bot.states import States
from bot.texts.text_manager import msg_text
from config.env_settings import Settings
from core.cache import Cache
from core.models import Coach, Profile
from core.services import APIService
from bot.functions.chat import contact_client, process_feedback_content
from bot.functions.menus import (
    show_main_menu,
    show_exercises_menu,
    manage_subscription,
    show_coaches_menu,
    show_profile_editing_menu,
    show_my_workouts_menu,
    my_clients_menu,
    show_my_profile_menu,
)
from bot.functions.profiles import assign_coach
from bot.functions.utils import handle_clients_pagination
from bot.functions.workout_plans import manage_program, cancel_subscription
from bot.functions.utils import del_msg

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
        await message.answer(msg_text("feedback", profile.language))
        await state.set_state(States.feedback)
        await del_msg(message)

    elif cb_data == "my_profile":
        await show_my_profile_menu(callback_query, profile, state)

    elif cb_data == "my_clients":
        await my_clients_menu(callback_query, profile, state)

    elif cb_data == "my_workouts":
        await show_my_workouts_menu(callback_query, profile, state)


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
    elif cb_data == "back":
        await show_main_menu(message, profile, state)
    else:
        await message.answer(
            msg_text("delete_confirmation", profile.language),
            reply_markup=yes_no_kb(profile.language),
        )
        await del_msg(message)
        await state.set_state(States.profile_delete)


@menu_router.message(States.feedback)
async def handle_feedback(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)

    if await process_feedback_content(message, profile):
        logger.info(f"Profile_id {profile.id} sent feedback")
        await message.answer(msg_text("feedback_sent", profile.language))
        await show_main_menu(message, profile, state)


@menu_router.callback_query(States.choose_coach)
async def choose_coach_menu(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    message = callback_query.message
    if message is None or not isinstance(message, Message):
        return
    cb_data = callback_query.data or ""

    if cb_data == "back":
        await show_main_menu(message, profile, state)
    else:
        coaches = await Cache.coach.get_coaches()
        if not coaches:
            await callback_query.answer(msg_text("no_coaches", profile.language), show_alert=True)
            return

        await state.set_state(States.coach_selection)
        await state.update_data(coaches=[Coach.model_dump(coach) for coach in coaches])
        await show_coaches_menu(message, coaches, bot)

    await del_msg(message)


@menu_router.callback_query(States.coach_selection)
async def coach_paginator(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    message = callback_query.message
    if message is None or not isinstance(message, Message):
        return
    data_str = callback_query.data or ""

    if data_str == "quit":
        await message.answer(
            msg_text("no_program", profile.language),
            reply_markup=choose_coach_kb(profile.language),
        )
        await state.set_state(States.choose_coach)
        await del_msg(message)
        return

    parts = data_str.split("_")
    if len(parts) != 2:
        await callback_query.answer(msg_text("out_of_range", profile.language))
        return

    action, index_str = parts
    try:
        index = int(index_str)
    except ValueError:
        await callback_query.answer(msg_text("out_of_range", profile.language))
        return

    data = await state.get_data()
    coaches_data = data.get("coaches", [])
    coaches = [Coach.model_validate(d) for d in coaches_data]

    if index < 0 or (index >= len(coaches) and action != "selected"):
        await callback_query.answer(msg_text("out_of_range", profile.language))
        return

    if action == "selected":
        await callback_query.answer(msg_text("saved", profile.language))
        coach_id = index
        coach = await Cache.coach.get_coach(coach_id)
        client = await Cache.client.get_client(profile.id)
        if client is not None and coach is not None:
            await assign_coach(coach, client)
        await state.set_state(States.gift)
        await message.answer(msg_text("gift", profile.language), reply_markup=gift_kb(profile.language))
        await del_msg(message)
    else:
        await show_coaches_menu(message, coaches, bot, current_index=index)


@menu_router.callback_query(States.show_clients)
async def client_paginator(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    message = callback_query.message
    if message is None or not isinstance(message, Message):
        return
    data_str = callback_query.data or ""

    if data_str == "back":
        await callback_query.answer()
        await show_main_menu(message, profile, state)
        return

    parts = data_str.split("_")
    if len(parts) != 2:
        await callback_query.answer(msg_text("out_of_range", profile.language))
        return

    action, client_id_str = parts
    if action == "contact":
        await contact_client(callback_query, profile, client_id_str, state)
        return
    if action == "program":
        await manage_program(callback_query, profile, client_id_str, state)
        return
    if action == "subscription":
        await manage_subscription(callback_query, profile.language, client_id_str, state)
        return

    try:
        index = int(client_id_str)
    except ValueError:
        await callback_query.answer(msg_text("out_of_range", profile.language))
        return

    await handle_clients_pagination(callback_query, profile, index, state)


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

    if cb_data == "back":
        await callback_query.answer()
        await state.set_state(States.select_service)
        await message.answer(
            msg_text("select_service", profile.language),
            reply_markup=select_service_kb(profile.language),
        )

    elif cb_data == "change_days":
        await callback_query.answer()
        await state.update_data(edit_mode=True)
        await state.set_state(States.workout_days)
        await message.answer(
            msg_text("select_days", profile.language),
            reply_markup=select_days_kb(profile.language, []),
        )

    elif cb_data == "contact":
        await callback_query.answer()
        client = await Cache.client.get_client(profile.id)
        if client is None or not client.assigned_to:
            return
        coach_id = client.assigned_to.pop()
        await state.update_data(recipient_id=coach_id, sender_name=client.name)
        await state.set_state(States.contact_coach)
        await message.answer(msg_text("enter_your_message", profile.language))

    elif cb_data == "cancel":
        logger.info(f"User {profile.id} requested to stop the subscription")
        await callback_query.answer(msg_text("subscription_canceled", profile.language), show_alert=True)

        if not callback_query.from_user:
            return
        user_chat = await bot.get_chat(callback_query.from_user.id)
        if user_chat is None:
            return
        contact = f"@{user_chat.username}" if user_chat.username else callback_query.from_user.id

        subscription = await Cache.workout.get_subscription(profile.id)
        if subscription is None:
            return

        order_id_opt = await APIService.payment.get_last_subscription_payment(profile.id)
        order_id = cast(str, order_id_opt)

        payment_date = datetime.strptime(subscription.payment_date, "%Y-%m-%d")
        next_payment_date = payment_date + relativedelta(months=1)

        async with aiohttp.ClientSession():
            await bot.send_message(
                Settings.ADMIN_ID,
                msg_text("subscription_cancel_request", Settings.ADMIN_LANG).format(
                    profile_id=profile.id,
                    contact=contact,
                    next_payment_date=next_payment_date.strftime("%Y-%m-%d"),
                    order_id=order_id,
                ),
            )

        await APIService.payment.unsubscribe(order_id)
        await cancel_subscription(next_payment_date, profile.id, subscription.id)
        logger.info(f"Subscription for profile_id {profile.id} deactivated")
        await show_main_menu(message, profile, state)

    else:
        await callback_query.answer()
        subscription = await Cache.workout.get_subscription(profile.id)
        if subscription is None:
            return
        workout_days = subscription.workout_days
        await state.update_data(
            exercises=subscription.exercises,
            days=workout_days,
            split=len(workout_days),
        )
        await show_exercises_menu(callback_query, state, profile)

    await del_msg(message)
