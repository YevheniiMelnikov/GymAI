import html
from contextlib import suppress
from dataclasses import dataclass
from typing import NamedTuple, Optional, cast

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, BotCommand, InputFile, FSInputFile
from aiohttp import ClientTimeout, ClientSession
from pydantic import ValidationError

from bot.texts import MessageText, TextManager, translate
from config.app_settings import settings
from bot.keyboards import select_language_kb
from bot.states import States
from bot.types.messaging import BotMessageProxy
from core.schemas import Profile
from core.services import APIService


class _WebAppTarget(NamedTuple):
    type_param: str
    source: str | None
    segment: str | None
    fragment: str | None


_WEBAPP_TARGETS: dict[str, _WebAppTarget] = {
    "program": _WebAppTarget("program", "direct", "program", "#/program"),
    "subscription": _WebAppTarget("program", "subscription", "subscriptions", "#/subscriptions"),
    "subscriptions": _WebAppTarget("program", "subscription", "subscriptions", "#/subscriptions"),
    "diets": _WebAppTarget("diet", None, None, None),
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
    """
    Shows an "in progress" notification.
    NOTE: show_alert=True only works for CallbackQuery targets.
    For Message targets, a new message is sent as alerts are not supported.
    """
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


@dataclass(frozen=True, slots=True)
class WebhookHealthcheckResult:
    ok: bool
    error: str | None


async def check_webhook_alive(ping_url: str, timeout_seconds: float = 5.0) -> WebhookHealthcheckResult:
    try:
        timeout = ClientTimeout(total=timeout_seconds)
        async with ClientSession(timeout=timeout) as session:
            async with session.get(ping_url) as resp:
                if resp.status != 200:
                    return WebhookHealthcheckResult(
                        ok=False,
                        error=f"Webhook healthcheck HTTP {resp.status} for {ping_url}",
                    )
                data = await resp.json(content_type=None)
                ok = bool(data.get("ok")) if isinstance(data, dict) else False
                if not ok:
                    return WebhookHealthcheckResult(
                        ok=False,
                        error=f"Webhook healthcheck returned invalid payload from {ping_url}: {data}",
                    )
            return WebhookHealthcheckResult(ok=True, error=None)
    except Exception as e:
        return WebhookHealthcheckResult(
            ok=False,
            error=f"Webhook healthcheck failed to reach {ping_url}: {e}",
        )


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


async def send_message(
    recipient: Profile,
    text: str,
    bot: Bot,
    state: FSMContext | None = None,
    reply_markup=None,
    include_incoming_message: bool = True,
    photo: str | InputFile | FSInputFile | None = None,
    video: str | InputFile | FSInputFile | None = None,
) -> None:
    def _resolve_media(
        media: str | InputFile | FSInputFile | None,
    ) -> str | InputFile | FSInputFile | None:
        if media is None:
            return None
        return getattr(media, "file_id", media)

    def _escape_html(value: str) -> str:
        return html.escape(value, quote=False)

    if state:
        data = await state.get_data()
        language = cast(str, data.get("recipient_language", ""))
        sender_name = cast(str, data.get("sender_name", ""))
    else:
        language = ""
        sender_name = ""

    recipient_profile = await APIService.profile.get_profile(recipient.id)
    if recipient_profile is None:
        from loguru import logger

        logger.error(f"Profile not found for recipient id {recipient.id} in send_message")
        return

    if include_incoming_message:
        try:
            template = translate(MessageText.ask_ai_response_template, language or recipient_profile.language or "ua")
        except Exception:
            template = "<b>{name}</b>:\n{message}"
        formatted_text = template.format(
            name=_escape_html(sender_name),
            message=_escape_html(text),
        )
    else:
        formatted_text = _escape_html(text)

    media_video = _resolve_media(video)
    media_photo = _resolve_media(photo)

    if media_video is not None:
        await bot.send_video(
            chat_id=recipient_profile.tg_id,
            video=media_video,
            caption=formatted_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
        )
    elif media_photo is not None:
        await bot.send_photo(
            chat_id=recipient_profile.tg_id,
            photo=media_photo,
            caption=formatted_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
        )
    else:
        await bot.send_message(
            chat_id=recipient_profile.tg_id,
            text=formatted_text,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
            parse_mode=ParseMode.HTML,
        )
