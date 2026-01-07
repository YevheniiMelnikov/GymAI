from contextlib import suppress
from typing import NamedTuple, Optional
from urllib.parse import ParseResult, parse_qsl, urlencode, urlparse, urlunparse

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, BotCommand
from aiohttp import ClientTimeout, ClientSession
from loguru import logger
from pydantic import ValidationError

from bot.texts import MessageText, TextManager, translate
from config.app_settings import settings
from bot.keyboards import select_language_kb
from bot.states import States
from bot.types.messaging import BotMessageProxy


class _WebAppTarget(NamedTuple):
    type_param: str
    source: str | None
    segment: str | None
    fragment: str | None


_WEBAPP_TARGETS: dict[str, _WebAppTarget] = {
    "program": _WebAppTarget("program", "direct", "program", "#/program"),
    "subscription": _WebAppTarget("program", "subscription", "subscriptions", "#/subscriptions"),
    "subscriptions": _WebAppTarget("program", "subscription", "subscriptions", "#/subscriptions"),
    "diets": _WebAppTarget("diet", None, "diets", "#/diets"),
    "payment": _WebAppTarget("payment", None, None, None),
    "topup": _WebAppTarget("topup", None, None, "#/topup"),
    "faq": _WebAppTarget("faq", "direct", "faq", "#/faq"),
    "weekly_survey": _WebAppTarget("weekly_survey", None, None, "#/weekly-survey"),
    "profile": _WebAppTarget("profile", None, None, "#/profile"),
}


async def del_msg(msg_obj: Message | CallbackQuery | None) -> None:
    if msg_obj is None:
        return
    message = msg_obj.message if isinstance(msg_obj, CallbackQuery) else msg_obj
    if message is None or not isinstance(message, Message):
        return
    with suppress(TelegramBadRequest):
        await message.delete()


async def answer_msg(msg_obj: Message | CallbackQuery | BotMessageProxy | None, *args, **kwargs) -> Message | None:
    if msg_obj is None:
        return None

    if isinstance(msg_obj, CallbackQuery):
        message = msg_obj.message
        if not isinstance(message, Message):
            return None
        target = message
    elif isinstance(msg_obj, (Message, BotMessageProxy)):
        target = msg_obj
    else:
        return None

    try:
        if "photo" in kwargs:
            photo = kwargs.pop("photo")
            return await target.answer_photo(photo, *args, **kwargs)

        if "document" in kwargs:
            doc = kwargs.pop("document")
            return await target.answer_document(doc, *args, **kwargs)

        if "video" in kwargs:
            video = kwargs.pop("video")
            return await target.answer_video(video, *args, **kwargs)

        # plain text
        if args:
            text, *rest = args
            return await target.answer(text, *rest, **kwargs)

        if "text" in kwargs:
            text = kwargs.pop("text")
            return await target.answer(text, **kwargs)

        raise ValueError("answer_msg: nothing to send")

    except TelegramBadRequest:
        return None


async def notify_request_in_progress(
    target: Message | CallbackQuery | BotMessageProxy,
    lang: str,
    *,
    show_alert: bool = True,
) -> None:
    text = translate(MessageText.request_in_progress, lang)
    if isinstance(target, CallbackQuery):
        await target.answer(text, show_alert=show_alert)
        return
    await answer_msg(target, text)


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


def get_webapp_url(
    page_type: str,
    lang: str | None = None,
    extra_params: dict[str, str] | None = None,
) -> str | None:
    source = settings.WEBAPP_PUBLIC_URL
    if not source:
        logger.error("WEBAPP_PUBLIC_URL is not configured; webapp button hidden")
        return None

    target = _WEBAPP_TARGETS.get(page_type, _WEBAPP_TARGETS["program"])
    parsed: ParseResult = urlparse(source)
    query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query_params["type"] = target.type_param

    if target.source:
        query_params["source"] = target.source
    else:
        query_params.pop("source", None)

    if target.segment:
        query_params["segment"] = target.segment
    else:
        query_params.pop("segment", None)

    if lang:
        query_params["lang"] = lang
    else:
        query_params.pop("lang", None)

    merged_params = dict(query_params)
    if extra_params:
        for key, value in extra_params.items():
            if value is None:
                merged_params.pop(key, None)
                continue
            merged_params[str(key)] = str(value)

    fragment = (target.fragment or "").lstrip("#")
    new_query = urlencode(merged_params)
    path = parsed.path or "/webapp/"
    updated = parsed._replace(path=path, query=new_query, fragment=fragment)
    return str(urlunparse(updated))


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


async def prompt_language_selection(message: Message, state: FSMContext) -> None:
    await state.clear()
    start_msg = await message.answer(translate(MessageText.start, settings.DEFAULT_LANG))
    language_msg = await message.answer(
        translate(MessageText.select_language, settings.DEFAULT_LANG),
        reply_markup=select_language_kb(),
    )
    message_ids: list[int] = []
    if start_msg:
        message_ids.append(start_msg.message_id)
    if language_msg:
        message_ids.append(language_msg.message_id)
    await state.update_data(message_ids=message_ids, chat_id=message.chat.id)
    await state.set_state(States.select_language)
