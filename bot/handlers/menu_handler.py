from contextlib import suppress
from datetime import datetime

from loguru import logger
from aiogram import Bot, Router
from aiogram.client.session import aiohttp
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from dateutil.relativedelta import relativedelta

from bot.keyboards import select_service_kb, choose_coach_kb, select_days_kb, gift_kb, yes_no_kb
from bot.states import States
from bot.texts.text_manager import msg_text
from config.env_settings import Settings
from core.cache import Cache
from core.services import APIService
from functions.chat import contact_client, process_feedback_content
from functions.menus import (
    show_main_menu,
    show_exercises_menu,
    manage_subscription,
    show_coaches_menu,
    show_profile_editing_menu,
    show_my_workouts_menu,
    my_clients_menu,
    show_my_profile_menu,
)
from functions.profiles import assign_coach, get_user_profile
from functions.utils import handle_clients_pagination
from functions.workout_plans import manage_program, cancel_subscription
from core.models import Coach, Profile

menu_router = Router()


@menu_router.callback_query(States.main_menu)
async def main_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if profile := Profile.from_dict(data.get("profile")):
        match callback_query.data:
            case "feedback":
                await callback_query.answer()
                await callback_query.message.answer(msg_text("feedback", profile.language))
                await state.set_state(States.feedback)
                await callback_query.message.delete()

            case "my_profile":
                await show_my_profile_menu(callback_query, profile, state)

            case "my_clients":
                await my_clients_menu(callback_query, profile, state)

            case "my_workouts":
                await show_my_workouts_menu(callback_query, profile, state)


@menu_router.callback_query(States.profile)
async def profile_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    data = await state.get_data()
    profile = Profile.from_dict(data["profile"])
    if callback_query.data == "profile_edit":
        await show_profile_editing_menu(callback_query.message, profile, state)
    elif callback_query.data == "back":
        await show_main_menu(callback_query.message, profile, state)
    else:
        await callback_query.message.answer(
            msg_text("delete_confirmation", profile.language), reply_markup=yes_no_kb(profile.language)
        )
        await callback_query.message.delete()
        await state.set_state(States.profile_delete)


@menu_router.message(States.feedback)
async def handle_feedback(message: Message, state: FSMContext) -> None:
    profile = await get_user_profile(message.from_user.id)
    if await process_feedback_content(message, profile):
        logger.info(f"Profile_id {profile.id} sent feedback")
        await message.answer(msg_text("feedback_sent", profile.language))
        await show_main_menu(message, profile, state)


@menu_router.callback_query(States.choose_coach)
async def choose_coach_menu(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
    profile = await get_user_profile(callback_query.from_user.id)
    if callback_query.data == "back":
        await show_main_menu(callback_query.message, profile, state)

    else:
        coaches = Cache.coach.get_coaches()
        if not coaches:
            await callback_query.answer(msg_text("no_coaches", profile.language), show_alert=True)
            return

        await state.set_state(States.coach_selection)
        await state.update_data(coaches=[Coach.to_dict(coach) for coach in coaches])
        await show_coaches_menu(callback_query.message, coaches, bot)

    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


@menu_router.callback_query(States.coach_selection)
async def coach_paginator(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
    profile = await get_user_profile(callback_query.from_user.id)

    if callback_query.data == "quit":
        await callback_query.message.answer(
            msg_text("no_program", profile.language),
            reply_markup=choose_coach_kb(profile.language),
        )
        await state.set_state(States.choose_coach)
        await callback_query.message.delete()
        return

    action, index = callback_query.data.split("_")
    index = int(index)
    data = await state.get_data()
    coaches = [Coach.from_dict(data) for data in data["coaches"]]
    if index < 0 or index >= len(coaches) and action != "selected":
        await callback_query.answer(msg_text("out_of_range", profile.language))
        return

    if action == "selected":
        await callback_query.answer(msg_text("saved", profile.language))
        coach_id = callback_query.data.split("_")[1]
        coach = Cache.coach.get_coach(int(coach_id))
        client = Cache.client.get_client(profile.id)
        await assign_coach(coach, client)
        await state.set_state(States.gift)
        await callback_query.message.answer(msg_text("gift", profile.language), reply_markup=gift_kb(profile.language))
        await callback_query.message.delete()
    else:
        await show_coaches_menu(callback_query.message, coaches, bot, current_index=index)


@menu_router.callback_query(States.show_clients)
async def client_paginator(callback_query: CallbackQuery, state: FSMContext):
    profile = await get_user_profile(callback_query.from_user.id)

    if callback_query.data == "back":
        await callback_query.answer()
        await show_main_menu(callback_query.message, profile, state)
        return

    action, client_id = callback_query.data.split("_")
    if action == "contact":
        await contact_client(callback_query, profile, client_id, state)
        return

    if action == "program":
        await manage_program(callback_query, profile, client_id, state)
        return

    if action == "subscription":
        await manage_subscription(callback_query, profile.language, client_id, state)
        return

    try:
        index = int(client_id)
    except ValueError:
        await callback_query.answer(msg_text("out_of_range", profile.language))
        return

    await handle_clients_pagination(callback_query, profile, index, state)


@menu_router.callback_query(States.show_subscription)
async def show_subscription_actions(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
    profile = await get_user_profile(callback_query.from_user.id)
    if callback_query.data == "back":
        await callback_query.answer()
        await state.set_state(States.select_service)
        await callback_query.message.answer(
            msg_text("select_service", profile.language),
            reply_markup=select_service_kb(profile.language),
        )

    elif callback_query.data == "change_days":
        await callback_query.answer()
        await state.update_data(edit_mode=True)
        await state.set_state(States.workout_days)
        await callback_query.message.answer(
            msg_text("select_days", profile.language), reply_markup=select_days_kb(profile.language, [])
        )

    elif callback_query.data == "contact":
        await callback_query.answer()
        client = Cache.client.get_client(profile.id)
        coach_id = client.assigned_to.pop()
        await state.update_data(recipient_id=coach_id, sender_name=client.name)
        await state.set_state(States.contact_coach)
        await callback_query.message.answer(msg_text("enter_your_message", profile.language))

    elif callback_query.data == "cancel":
        logger.info(f"User {profile.id} requested to stop the subscription")
        await callback_query.answer(msg_text("subscription_canceled", profile.language), show_alert=True)
        user = await bot.get_chat(callback_query.from_user.id)
        contact = f"@{user.username}" if user.username else callback_query.from_user.id
        subscription = Cache.workout.get_subscription(profile.id)
        order_id = await APIService.payment.get_last_subscription_payment(profile.id)
        payment_date = datetime.strptime(subscription.payment_date, "%Y-%m-%d")
        next_payment_date = payment_date + relativedelta(months=1)
        async with aiohttp.ClientSession():
            await bot.send_message(
                Settings.OWNER_ID,
                msg_text("subscription_cancel_request", Settings.OWNER_LANG).format(
                    profile_id=profile.id,
                    contact=contact,
                    next_payment_date=next_payment_date.strftime("%Y-%m-%d"),
                    order_id=order_id,
                ),
            )

        await APIService.payment.unsubscribe(order_id)
        await cancel_subscription(next_payment_date, profile.id, subscription.id)
        logger.info(f"Subscription for profile_id {profile.id} deactivated")
        await show_main_menu(callback_query.message, profile, state)

    else:
        await callback_query.answer()
        subscription = Cache.workout.get_subscription(profile.id)
        workout_days = subscription.workout_days
        await state.update_data(exercises=subscription.exercises, days=workout_days, split=len(workout_days))
        await show_exercises_menu(callback_query, state, profile)

    with suppress(TelegramBadRequest):
        await callback_query.message.delete()
