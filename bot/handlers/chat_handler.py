from __future__ import annotations

from contextlib import suppress

from loguru import logger
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.keyboards import new_message_kb, workout_results_kb
from bot.states import States
from config.env_settings import Settings
from core.cache import Cache
from core.services import APIService
from functions.chat import send_message
from functions.exercises import edit_subscription_exercises
from functions.menus import show_main_menu, manage_subscription, show_exercises_menu
from bot.texts.text_manager import msg_text
from functions.text_utils import _msg
from functions.utils import program_menu_pagination
from functions.profiles import Profile

chat_router = Router()


@chat_router.message(States.contact_client, F.text | F.photo | F.video)
async def contact_client(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    assert profile is not None

    client = await Cache.client.get_client(data.get("recipient_id"))
    assert client is not None
    client_profile = await APIService.profile.get_profile(client.id)
    assert client_profile is not None
    coach = await Cache.coach.get_coach(profile.id)
    assert coach is not None

    if client.status == "waiting_for_text":
        await Cache.client.update_client(client.id, {"status": "default"})

    await state.update_data(sender_name=coach.name, recipient_language=client_profile.language)

    caption = message.caption or ""
    if message.photo:
        await send_message(
            client,
            caption,
            state,
            reply_markup=new_message_kb(client_profile.language, profile.id),
            photo=message.photo[-1],
        )
    elif message.video:
        await send_message(
            client,
            caption,
            state,
            reply_markup=new_message_kb(client_profile.language, profile.id),
            video=message.video,
        )
    else:
        await send_message(
            client,
            message.text or "",
            state,
            reply_markup=new_message_kb(client_profile.language, profile.id),
        )

    await message.answer(msg_text("message_sent", profile.language))
    logger.debug(f"Coach {profile.id} sent message to client {client.id}")
    await show_main_menu(message, profile, state)


@chat_router.message(States.contact_coach, F.text | F.photo | F.video)
async def contact_coach(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    assert profile is not None

    coach = await Cache.coach.get_coach(data.get("recipient_id"))
    assert coach is not None
    coach_profile = await APIService.profile.get_profile(coach.id)
    assert coach_profile is not None
    client = await Cache.client.get_client(profile.id)
    assert client is not None

    await state.update_data(sender_name=client.name, recipient_language=coach_profile.language)

    caption = message.caption or ""
    if message.photo:
        await send_message(
            coach,
            caption,
            state,
            reply_markup=new_message_kb(coach_profile.language, profile.id),
            photo=message.photo[-1],
        )
    elif message.video:
        await send_message(
            coach,
            caption,
            state,
            reply_markup=new_message_kb(coach_profile.language, profile.id),
            video=message.video,
        )
    else:
        await send_message(
            coach,
            message.text or "",
            state,
            reply_markup=new_message_kb(coach_profile.language, profile.id),
        )

    await message.answer(msg_text("message_sent", profile.language))
    logger.debug(f"Client {profile.id} sent message to coach {coach.id}")
    await show_main_menu(message, profile, state)


@chat_router.callback_query(F.data.startswith("yes_") | F.data.startswith("no_"))
async def have_you_trained(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    assert profile is not None
    subscription = await Cache.workout.get_subscription(profile.id)
    assert subscription is not None

    try:
        _, weekday = callback_query.data.split("_", 1)
    except ValueError:
        await callback_query.answer("❓")
        return

    workout_days = subscription.workout_days or []
    day_index = workout_days.index(weekday) if weekday in workout_days else -1

    if callback_query.data.startswith("yes"):
        exercises = subscription.exercises.get(str(day_index)) or subscription.exercises.get(weekday)
        await state.update_data(exercises=exercises, day=weekday, day_index=day_index)
        await callback_query.answer("🔥")
        await _msg(callback_query.message).answer(
            msg_text("workout_results", profile.language),
            reply_markup=workout_results_kb(profile.language),
        )
        await _msg(callback_query.message).delete()
        await state.set_state(States.workout_survey)
    else:
        await callback_query.answer("😢")
        await _msg(callback_query.message).delete()
        logger.debug(f"User {profile.id} reported no training on {weekday}")


@chat_router.callback_query(F.data.in_(["quit", "later"]))
async def close_notification(callback_query: CallbackQuery, state: FSMContext) -> None:
    await _msg(callback_query.message).delete()
    data = await state.get_data()
    profile_dict = data.get("profile")
    if profile_dict:
        profile = Profile.model_validate(profile_dict)
        await show_main_menu(_msg(callback_query.message), profile, state)


@chat_router.callback_query(F.data == "subscription_view")
async def subscription_view(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    assert profile is not None
    subscription = await Cache.workout.get_subscription(profile.id)
    assert subscription is not None

    await state.update_data(
        exercises=subscription.exercises,
        split=len(subscription.workout_days),
        days=subscription.workout_days,
        subscription=True,
    )
    await show_exercises_menu(callback_query, state, profile)


@chat_router.callback_query(F.data.startswith("answer"))
async def answer_message(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    assert profile is not None

    recipient_id = int(callback_query.data.split("_", 1)[1])
    if profile.status == "client":
        sender = await Cache.client.get_client(profile.id)
        state_to_set = States.contact_coach
    else:
        sender = await Cache.coach.get_coach(profile.id)
        state_to_set = States.contact_client
        client = await Cache.client.get_client(recipient_id)
        if client and client.status == "waiting_for_text":
            await Cache.client.update_client(recipient_id, {"status": "default"})

    assert sender is not None

    await _msg(callback_query.message).answer(msg_text("enter_your_message", profile.language))
    await state.clear()
    await state.update_data(recipient_id=recipient_id, sender_name=sender.name)
    await state.set_state(state_to_set)


@chat_router.callback_query(F.data.in_(["previous", "next"]))
async def navigate_days(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    assert profile is not None

    program = await Cache.workout.get_program(profile.id)
    if data.get("subscription"):
        subscription = await Cache.workout.get_subscription(profile.id)
        assert subscription is not None
        split_number = len(subscription.workout_days)
        exercises = subscription.exercises
    else:
        assert program is not None
        split_number = program.split_number
        exercises = program.exercises_by_day

    await state.update_data(exercises=exercises, split=split_number, client=True)
    await program_menu_pagination(state, callback_query)


@chat_router.callback_query(F.data.startswith("edit_"))
async def edit_subscription(callback_query: CallbackQuery, state: FSMContext) -> None:
    await edit_subscription_exercises(callback_query, state)


@chat_router.callback_query(F.data.startswith("create"))
async def create_workouts(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    assert profile is not None

    await state.clear()
    _, service, client_id = callback_query.data.split("_", 2)
    await state.update_data(client_id=client_id)

    if service == "subscription":
        await manage_subscription(callback_query, profile.language, client_id, state)
    else:
        await _msg(callback_query.message).answer(msg_text("workouts_number", profile.language))
        await state.set_state(States.workouts_number)
        with suppress(TelegramBadRequest):
            await _msg(callback_query.message).delete()


@chat_router.callback_query(F.data.startswith("approve"))
async def approve_coach(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile_id = int(callback_query.data.split("_", 1)[1])
    await APIService.profile.update_coach_profile(profile_id, {"verified": True})
    await Cache.coach.update_coach(profile_id, {"verified": True})
    await callback_query.answer("👍")
    coach = await Cache.coach.get_coach(profile_id)
    profile = await APIService.profile.get_profile(profile_id)
    lang = profile.language if profile else Settings.BOT_LANG
    if coach:
        await send_message(coach, msg_text("coach_verified", lang), state, include_incoming_message=False)
    await _msg(callback_query.message).delete()
    logger.info(f"Coach verification for profile_id {profile_id} approved")


@chat_router.callback_query(F.data.startswith("decline"))
async def decline_coach(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile_id = int(callback_query.data.split("_", 1)[1])
    await callback_query.answer("👎")
    coach = await Cache.coach.get_coach(profile_id)
    profile = await APIService.profile.get_profile(profile_id)
    lang = profile.language if profile else Settings.BOT_LANG
    if coach:
        await send_message(coach, msg_text("coach_declined", lang), state, include_incoming_message=False)
    await _msg(callback_query.message).delete()
    logger.info(f"Coach verification for profile_id {profile_id} declined")
