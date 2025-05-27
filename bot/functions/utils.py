from __future__ import annotations

import secrets
import string
from contextlib import suppress
from typing import Optional, Any, cast

import aiohttp
from pydantic_core import ValidationError

from loguru import logger
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, CallbackQuery, Message

from bot.keyboards import program_edit_kb, program_view_kb, subscription_manage_kb, profile_menu_kb
from bot.singleton import bot as bot_instance
from bot.states import States
from config.env_settings import Settings
from core.cache import Cache
from core.exceptions import UserServiceError
from core.services import APIService
from core.services.outer.gstorage_service import avatar_manager
from core.validators import validate_or_raise
from bot.functions import text_utils
from bot.functions import menus, profiles
from core.models import Client, Profile, Coach, DayExercises, Exercise
from bot.texts.text_manager import msg_text, TextManager


def get_bot() -> Bot:
    return cast(Bot, bot_instance)


async def short_url(url: str) -> str:
    if url.startswith("https://tinyurl.com/"):
        return url

    async with aiohttp.ClientSession() as session:
        params = {"url": url}
        async with session.get("http://tinyurl.com/api-create.php", params=params) as response:
            response_text = await response.text()
            if response.status == 200:
                return response_text
            else:
                logger.error(f"Failed to process URL: {response.status}, {response_text}")
                return url


async def set_bot_commands(lang: Optional[str] = None) -> None:
    lang = lang or Settings.DEFAULT_LANG
    command_texts = TextManager.commands
    commands = [BotCommand(command=cmd, description=desc[lang]) for cmd, desc in command_texts.items()]
    bot = get_bot()
    await bot.set_my_commands(commands)


async def program_menu_pagination(state: FSMContext, callback_query: CallbackQuery) -> None:
    profile = await profiles.get_user_profile(callback_query.from_user.id)
    assert profile

    if callback_query.data == "quit":
        await menus.my_clients_menu(callback_query, profile, state)
        return

    data = await state.get_data()
    current_day = data.get("day_index", 0)
    exercises = data.get("exercises", [])

    if isinstance(exercises, dict):
        exercises = [
            DayExercises(day=k, exercises=[Exercise.model_validate(e) if isinstance(e, dict) else e for e in v])
            for k, v in exercises.items()
        ]

    split_number = data.get("split")
    assert split_number is not None

    if data.get("client"):
        reply_markup = program_view_kb(profile.language)
        state_to_set = States.program_view
    else:
        reply_markup = (
            subscription_manage_kb(profile.language) if data.get("subscription") else program_edit_kb(profile.language)
        )
        state_to_set = States.subscription_manage if data.get("subscription") else States.program_edit

    await state.set_state(state_to_set)
    current_day += -1 if callback_query.data in ["prev_day", "previous"] else 1

    if current_day < 0 or current_day >= split_number:
        current_day = max(0, min(current_day, split_number - 1))
        await callback_query.answer(msg_text("out_of_range", profile.language))
        await state.update_data(day_index=current_day)
        return

    await state.update_data(day_index=current_day)

    program_text = await text_utils.format_program(exercises, current_day)
    days = data.get("days", [])
    next_day = (
        text_utils.get_translated_week_day(profile.language, days[current_day]).lower()
        if data.get("subscription")
        else current_day + 1
    )
    with suppress(TelegramBadRequest):
        message = callback_query.message
        if message and isinstance(message, Message):
            await message.edit_text(
                msg_text("program_page", profile.language).format(program=program_text, day=next_day),
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )

    await callback_query.answer()


async def handle_clients_pagination(
    callback_query: CallbackQuery, profile: Profile, index: int, state: FSMContext
) -> None:
    data = await state.get_data()
    clients = [
        validate_or_raise(client_data, Client, context="clients list") for client_data in data.get("clients", [])
    ]

    if not clients:
        await callback_query.answer(msg_text("no_clients", profile.language))
        return

    if index < 0 or index >= len(clients):
        await callback_query.answer(msg_text("out_of_range", profile.language))
        return

    message = callback_query.message
    if message and isinstance(message, Message):
        await menus.show_clients(message, clients, state, index)


async def delete_messages(state: FSMContext) -> None:
    data = await state.get_data()
    message_ids = data.get("message_ids", [])
    chat_id = data.get("chat_id")
    if chat_id is None:
        return
    bot = get_bot()
    for message_id in message_ids:
        with suppress(TelegramBadRequest, ValidationError):
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
    await state.update_data(message_ids=[])


def generate_order_id() -> str:
    characters = string.ascii_letters + string.digits
    return "".join(secrets.choice(characters) for _ in range(12))


async def fetch_user(profile: Profile) -> Client | Coach:
    if profile.status == "client":
        try:
            return await Cache.client.get_client(profile.id)
        except UserServiceError as e:
            logger.info(f"Client data for profile {profile.id} not found: {e}")
            client = await APIService.profile.get_client_by_profile_id(profile.id)
            if client is None:
                raise ValueError(f"Profile not found for id {profile.id}")
            await Cache.client.update_client(profile.id, client.model_dump())
            return client

    elif profile.status == "coach":
        try:
            return await Cache.coach.get_coach(profile.id)
        except UserServiceError as e:
            logger.info(f"Coach data for profile {profile.id} not found: {e}")
            coach = await APIService.profile.get_coach_by_profile_id(profile.id)
            if coach is None:
                raise ValueError(f"Profile not found for id {profile.id}")
            await Cache.coach.update_coach(profile.id, coach.model_dump())
            return coach

    else:
        raise ValueError(f"Unknown profile status: {profile.status}")


async def answer_profile(cbq: CallbackQuery, profile: Profile, user: Coach | Client, text: str) -> None:
    message = cbq.message
    if not message or not isinstance(message, Message):
        return

    if (
        profile.status == "coach"
        and isinstance(user, Coach)
        and hasattr(user, "profile_photo")
        and getattr(user, "profile_photo", None)
    ):
        photo_url = f"https://storage.googleapis.com/{avatar_manager.bucket_name}/{user.profile_photo}"
        try:
            await message.answer_photo(photo_url, text, reply_markup=profile_menu_kb(profile.language))
            return
        except TelegramBadRequest:
            logger.warning("Photo not found for coach %s", profile.id)

    await message.answer(text, reply_markup=profile_menu_kb(profile.language))


def serialize_day_exercises(exercises: list[DayExercises]) -> dict[str, list[dict[str, Any]]]:
    return {day.day: [e.model_dump() for e in day.exercises] for day in exercises if isinstance(day, DayExercises)}


async def answer_msg(msg_obj: Message | CallbackQuery | None, *args, **kwargs) -> Message | None:
    if msg_obj is None:
        return None
    message = msg_obj.message if isinstance(msg_obj, CallbackQuery) else msg_obj
    if message is None or not isinstance(message, Message):
        return None
    try:
        return await message.answer(*args, **kwargs)
    except TelegramBadRequest:
        return None


async def del_msg(msg_obj: Message | CallbackQuery | None) -> None:
    if msg_obj is None:
        return
    message = msg_obj.message if isinstance(msg_obj, CallbackQuery) else msg_obj
    if message is None or not isinstance(message, Message):
        return
    with suppress(TelegramBadRequest):
        await message.delete()
