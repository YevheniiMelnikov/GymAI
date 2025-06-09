from __future__ import annotations

from contextlib import suppress
from typing import cast

from loguru import logger
from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.keyboards import new_message_kb, workout_results_kb
from bot.states import States
from core.cache import Cache
from core.enums import ClientStatus
from core.schemas import Profile
from core.services import APIService
from bot.utils.chat import send_message
from bot.utils.exercises import edit_subscription_exercises
from bot.utils.menus import show_main_menu, manage_subscription, show_exercises_menu, program_menu_pagination
from bot.texts.text_manager import msg_text
from bot.utils.other import del_msg, answer_msg

chat_router = Router()


@chat_router.message(States.contact_client)
async def contact_client(message: Message, state: FSMContext, bot: Bot) -> None:
    if not (message.text or message.photo or message.video):
        return

    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    assert profile is not None

    recipient_id = data.get("recipient_id")
    if recipient_id is None:
        logger.error("Recipient ID is None in contact_client handler")
        await answer_msg(message, "Internal error: recipient not specified.")
        return
    client = await Cache.client.get_client(recipient_id)
    assert client is not None
    client_profile = await APIService.profile.get_profile(client.profile)
    assert client_profile is not None
    coach = await Cache.coach.get_coach(profile.id)
    assert coach is not None

    if client.status == ClientStatus.waiting_for_text:
        await Cache.client.update_client(client.id, {"status": ClientStatus.default})

    await state.update_data(sender_name=coach.name, recipient_language=client_profile.language)

    caption = message.caption or ""
    if message.photo:
        await send_message(
            recipient=client,
            text=caption,
            bot=bot,
            state=state,
            reply_markup=new_message_kb(client_profile.language, profile.id),
            photo=message.photo[-1],
        )
    elif message.video:
        await send_message(
            recipient=client,
            text=caption,
            bot=bot,
            state=state,
            reply_markup=new_message_kb(client_profile.language, profile.id),
            video=message.video,
        )
    else:
        await send_message(
            recipient=client,
            text=message.text or "",
            bot=bot,
            state=state,
            reply_markup=new_message_kb(client_profile.language, profile.id),
        )

    await answer_msg(message, msg_text("message_sent", profile.language))
    logger.debug(f"Coach {profile.id} sent message to client {client.id}")
    await show_main_menu(message, profile, state)


@chat_router.message(States.contact_coach)
async def contact_coach(message: Message, state: FSMContext, bot: Bot) -> None:
    if not (message.text or message.photo or message.video):
        return

    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    assert profile is not None

    recipient_id = data.get("recipient_id")
    if recipient_id is None:
        logger.error("Recipient ID is None in contact_coach handler")
        await answer_msg(message, "Internal error: recipient not specified.")
        return
    coach = await Cache.coach.get_coach(recipient_id)
    assert coach is not None
    coach_profile = await APIService.profile.get_profile(coach.profile)
    assert coach_profile is not None
    client = await Cache.client.get_client(profile.id)
    assert client is not None

    await state.update_data(sender_name=client.name, recipient_language=coach_profile.language)

    caption = message.caption or ""
    if message.photo:
        await send_message(
            recipient=coach,
            text=caption,
            bot=bot,
            state=state,
            reply_markup=new_message_kb(coach_profile.language, profile.id),
            photo=message.photo[-1],
        )
    elif message.video:
        await send_message(
            recipient=coach,
            text=caption,
            bot=bot,
            state=state,
            reply_markup=new_message_kb(coach_profile.language, profile.id),
            video=message.video,
        )
    else:
        await send_message(
            recipient=coach,
            text=message.text or "",
            bot=bot,
            state=state,
            reply_markup=new_message_kb(coach_profile.language, profile.id),
        )

    await answer_msg(message, msg_text("message_sent", profile.language))
    logger.debug(f"Client {profile.id} sent message to coach {coach.id}")
    await show_main_menu(message, profile, state)


@chat_router.callback_query()
async def have_you_trained(callback_query: CallbackQuery, state: FSMContext) -> None:
    if not callback_query.data or not (callback_query.data.startswith("yes_") or callback_query.data.startswith("no_")):
        return

    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    assert profile is not None
    subscription = await Cache.workout.get_latest_subscription(profile.id)
    assert subscription is not None

    data_str = cast(str, callback_query.data)
    try:
        _, weekday = data_str.split("_", 1)
    except ValueError:
        await callback_query.answer("❓")
        return

    workout_days = subscription.workout_days or []
    day_index = workout_days.index(weekday) if weekday in workout_days else -1

    if data_str.startswith("yes"):
        exercises = next(
            (
                day.exercises
                for day in subscription.exercises
                if day.day == weekday or subscription.exercises.index(day) == day_index
            ),
            [],
        )

        await state.update_data(exercises=exercises, day=weekday, day_index=day_index)
        await callback_query.answer("🔥")
        if callback_query.message and isinstance(callback_query.message, Message):
            await answer_msg(
                callback_query.message,
                msg_text("workout_results", profile.language),
                reply_markup=workout_results_kb(profile.language),
            )
            await del_msg(callback_query.message)
        await state.set_state(States.workout_survey)
    else:
        await callback_query.answer("😢")
        if callback_query.message and isinstance(callback_query.message, Message):
            await del_msg(callback_query.message)
        logger.debug(f"User {profile.id} reported no training on {weekday}")


@chat_router.callback_query()
async def close_notification(callback_query: CallbackQuery, state: FSMContext) -> None:
    if not callback_query.data or callback_query.data not in ["quit", "later"]:
        return

    if callback_query.message and isinstance(callback_query.message, Message):
        await del_msg(callback_query.message)
    data = await state.get_data()
    profile_dict = data.get("profile")
    if profile_dict:
        profile = Profile.model_validate(profile_dict)
        if callback_query.message and isinstance(callback_query.message, Message):
            await show_main_menu(callback_query.message, profile, state)


@chat_router.callback_query()
async def subscription_view(callback_query: CallbackQuery, state: FSMContext) -> None:
    if callback_query.data != "subscription_view":
        return

    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    assert profile is not None
    subscription = await Cache.workout.get_latest_subscription(profile.id)
    assert subscription is not None

    await state.update_data(
        exercises=subscription.exercises,
        split=len(subscription.workout_days),
        days=subscription.workout_days,
        subscription=True,
    )
    await show_exercises_menu(callback_query, state, profile)


@chat_router.callback_query()
async def answer_message(callback_query: CallbackQuery, state: FSMContext) -> None:
    if not callback_query.data or not callback_query.data.startswith("answer"):
        return

    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    assert profile is not None

    data_str = cast(str, callback_query.data)
    try:
        recipient_id = int(data_str.split("_", 1)[1])
    except (IndexError, ValueError):
        await callback_query.answer("Invalid recipient id")
        return

    if profile.status == "client":
        sender = await Cache.client.get_client(profile.id)
        state_to_set = States.contact_coach
    else:
        sender = await Cache.coach.get_coach(profile.id)
        state_to_set = States.contact_client
        client = await Cache.client.get_client(recipient_id)
        if client and client.status == ClientStatus.waiting_for_text:
            await Cache.client.update_client(client.id, {"status": ClientStatus.default})

    assert sender is not None

    if callback_query.message and isinstance(callback_query.message, Message):
        await answer_msg(callback_query.message, msg_text("enter_your_message", profile.language))
    await state.clear()
    await state.update_data(recipient_id=recipient_id, sender_name=sender.name)
    await state.set_state(state_to_set)


@chat_router.callback_query()
async def navigate_days(callback_query: CallbackQuery, state: FSMContext) -> None:
    if not callback_query.data or callback_query.data not in ["previous", "next"]:
        return

    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    assert profile is not None
    client = await Cache.client.get_client(profile.id)
    program = await Cache.workout.get_program(client.id)

    if data.get("subscription"):
        subscription = await Cache.workout.get_latest_subscription(client.id)
        assert subscription is not None
        split_number = len(subscription.workout_days)
        exercises = subscription.exercises
    else:
        assert program is not None
        split_number = program.split_number
        exercises = program.exercises_by_day

    await state.update_data(exercises=exercises, split=split_number, client=True)
    await program_menu_pagination(state, callback_query)


@chat_router.callback_query()
async def edit_subscription(callback_query: CallbackQuery, state: FSMContext) -> None:
    if not callback_query.data or not callback_query.data.startswith("edit_"):
        return

    await edit_subscription_exercises(callback_query, state)


@chat_router.callback_query()
async def create_workouts(callback_query: CallbackQuery, state: FSMContext) -> None:
    if not callback_query.data or not callback_query.data.startswith("create"):
        return

    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    assert profile is not None

    await state.clear()
    _, service, client_id = cast(str, callback_query.data).split("_", 2)
    await state.update_data(client_id=client_id)

    if service == "subscription":
        await manage_subscription(callback_query, profile.language, client_id, state)
    else:
        if callback_query.message and isinstance(callback_query.message, Message):
            await answer_msg(callback_query.message, msg_text("workouts_number", profile.language))
        await state.set_state(States.workouts_number)
        with suppress(TelegramBadRequest):
            if callback_query.message and isinstance(callback_query.message, Message):
                await del_msg(callback_query.message)
