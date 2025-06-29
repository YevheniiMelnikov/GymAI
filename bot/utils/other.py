from __future__ import annotations

import re
import secrets
import string
from contextlib import suppress
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Optional

import aiohttp
from dependency_injector.wiring import inject, Provide
from pydantic_core import ValidationError

from loguru import logger
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, CallbackQuery, Message

from config.env_settings import settings
from bot.texts.text_manager import TextManager
from core.enums import CommandName
from core.containers import App


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


async def set_bot_commands(bot: Bot, lang: Optional[str] = None) -> None:
    lang = lang or settings.DEFAULT_LANG
    command_texts = TextManager.commands
    commands = [BotCommand(command=cmd, description=desc[lang]) for cmd, desc in command_texts.items()]
    await bot.set_my_commands(commands)


@inject
async def delete_messages(state: FSMContext, bot: Bot = Provide[App.bot]) -> None:
    data = await state.get_data()
    message_ids = data.get("message_ids", [])
    chat_id = data.get("chat_id")
    if chat_id is None:
        return
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
    if not isinstance(message, Message):
        return None

    try:
        if "photo" in kwargs:
            photo = kwargs.pop("photo")
            return await message.answer_photo(photo, *args, **kwargs)

        if "document" in kwargs:
            doc = kwargs.pop("document")
            return await message.answer_document(doc, *args, **kwargs)

        if "video" in kwargs:
            video = kwargs.pop("video")
            return await message.answer_video(video, *args, **kwargs)

        # plain text
        if args:
            text, *rest = args
            return await message.answer(text, *rest, **kwargs)

        if "text" in kwargs:
            text = kwargs.pop("text")
            return await message.answer(text, **kwargs)

        raise ValueError("answer_msg: nothing to send")

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


def parse_price(raw: str) -> Decimal:
    price_re = re.compile(r"^\d{1,8}(\.\d{1,2})?$")

    if not price_re.fullmatch(raw):
        raise ValueError("Price must be 0-99 999 999.99 (max 2 decimals)")
    try:
        return Decimal(raw).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal value") from exc
