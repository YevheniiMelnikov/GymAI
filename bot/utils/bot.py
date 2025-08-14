from __future__ import annotations

from contextlib import suppress
from typing import Optional
from urllib.parse import urlparse

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, BotCommand
from aiohttp import ClientTimeout, ClientSession
from loguru import logger
from pydantic import ValidationError

from bot.texts import TextManager
from config.app_settings import settings


async def del_msg(msg_obj: Message | CallbackQuery | None) -> None:
    if msg_obj is None:
        return
    message = msg_obj.message if isinstance(msg_obj, CallbackQuery) else msg_obj
    if message is None or not isinstance(message, Message):
        return
    with suppress(TelegramBadRequest):
        await message.delete()


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


async def delete_messages(state: FSMContext, bot: Bot | None = None) -> None:
    if bot is None:
        from core.containers import get_container

        bot = get_container().bot()

    data = await state.get_data()
    message_ids = data.get("message_ids", [])
    chat_id = data.get("chat_id")
    if chat_id is None:
        return
    for message_id in message_ids:
        with suppress(TelegramBadRequest, ValidationError):
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
    await state.update_data(message_ids=[])


async def set_bot_commands(bot: Bot, lang: Optional[str] = None) -> None:
    lang = lang or settings.DEFAULT_LANG
    command_texts = TextManager.commands
    commands = [BotCommand(command=cmd, description=desc[lang]) for cmd, desc in command_texts.items()]
    await bot.set_my_commands(commands)


def get_webapp_url(page_type: str) -> str | None:
    source = settings.WEBAPP_PUBLIC_URL
    if not source:
        logger.error("WEBAPP_PUBLIC_URL is not configured; webapp button hidden")
        return None
    parsed = urlparse(source)
    host = parsed.netloc or parsed.path.split("/")[0]
    base = f"{parsed.scheme or 'https'}://{host}"
    return f"{base}/webapp/?type={page_type}"


def build_ping_url(webhook_url: str, path: str) -> str:
    url = webhook_url.rstrip("/")
    p = path.rstrip("/")
    if p and url.endswith(p):
        base = url[: -len(p)]
        base = base.rstrip("/")
    else:
        base = url
    return f"{base}/__ping"


async def check_webhook_alive(ping_url: str, timeout_seconds: float = 5.0) -> bool:
    try:
        timeout = ClientTimeout(total=timeout_seconds)
        async with ClientSession(timeout=timeout) as session:
            async with session.get(ping_url) as resp:
                if resp.status != 200:
                    logger.error(f"Webhook healthcheck HTTP {resp.status} for {ping_url}")
                    return False
                data = await resp.json(content_type=None)
                ok = bool(data.get("ok")) if isinstance(data, dict) else False
                if not ok:
                    logger.error(f"Webhook healthcheck returned invalid payload from {ping_url}: {data}")
                return ok
    except Exception as e:
        logger.error(f"Webhook healthcheck failed to reach {ping_url}: {e}")
        return False
