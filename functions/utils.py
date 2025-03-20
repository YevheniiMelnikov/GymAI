import secrets
import string
from contextlib import suppress
from typing import Optional

import aiohttp
from pydantic_core import ValidationError

from common.logger import logger
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, CallbackQuery

from bot.keyboards import program_edit_kb, program_view_kb, subscription_manage_kb
from bot.states import States
from common.settings import settings
from functions import menus, profiles, text_utils
from core.models import Client
from bot.texts.text_manager import msg_text, TextManager

bot = Bot(settings.BOT_TOKEN)


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
    lang = lang or settings.DEFAULT_BOT_LANGUAGE
    command_texts = TextManager.commands
    commands = [BotCommand(command=cmd, description=desc[lang]) for cmd, desc in command_texts.items()]
    await bot.set_my_commands(commands)


async def program_menu_pagination(state: FSMContext, callback_query: CallbackQuery) -> None:
    profile = await profiles.get_user_profile(callback_query.from_user.id)

    if callback_query.data == "quit":
        await menus.my_clients_menu(callback_query, profile, state)
        return

    data = await state.get_data()
    current_day = data.get("day_index", 0)
    exercises = data.get("exercises", {})
    split_number = data.get("split")

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
        await callback_query.message.edit_text(
            msg_text("program_page", profile.language).format(program=program_text, day=next_day),
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )

    await callback_query.answer()


async def handle_clients_pagination(callback_query: CallbackQuery, profile, index: int, state: FSMContext) -> None:
    data = await state.get_data()
    clients = [Client.from_dict(data) for data in data.get("clients")]

    if not clients:
        await callback_query.answer(msg_text("no_clients", profile.language))
        return

    if index < 0 or index >= len(clients):
        await callback_query.answer(msg_text("out_of_range", profile.language))
        return

    await menus.show_clients(callback_query.message, clients, state, index)


async def delete_messages(state: FSMContext) -> None:
    data = await state.get_data()
    message_ids = data.get("message_ids", [])
    for message_id in message_ids:
        with suppress(TelegramBadRequest, ValidationError):
            await bot.delete_message(chat_id=data.get("chat_id"), message_id=message_id)
    await state.update_data(message_ids=[])


def generate_order_id() -> str:
    characters = string.ascii_letters + string.digits
    return "".join(secrets.choice(characters) for _ in range(12))
