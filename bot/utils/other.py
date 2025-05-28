from __future__ import annotations

import secrets
import string
from contextlib import suppress
from typing import Optional, cast

import aiohttp
from pydantic_core import ValidationError

from loguru import logger
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, CallbackQuery, Message

from bot.singleton import bot as bot_instance
from config.env_settings import Settings
from bot.texts.text_manager import TextManager


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
