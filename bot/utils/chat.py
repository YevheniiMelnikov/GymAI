import html
from typing import Iterable, cast

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, InputFile, Message

from bot.texts import MessageText, translate
from bot.utils.bot import answer_msg
from config.app_settings import settings
from core.schemas import Profile
from core.services import APIService


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


async def process_feedback_content(message: Message, profile: Profile, bot: Bot) -> bool:
    text = translate(MessageText.new_feedback, settings.ADMIN_LANG).format(
        profile_id=profile.id,
        feedback=message.text or message.caption or "",
    )

    if message.text:
        await bot.send_message(
            chat_id=settings.ADMIN_ID,
            text=text,
            parse_mode=ParseMode.HTML,
        )
        return True

    if message.photo:
        photo_id = message.photo[-1].file_id
        await bot.send_message(chat_id=settings.ADMIN_ID, text=text, parse_mode=ParseMode.HTML)
        await bot.send_photo(chat_id=settings.ADMIN_ID, photo=photo_id)
        return True

    if message.video:
        await bot.send_message(chat_id=settings.ADMIN_ID, text=text, parse_mode=ParseMode.HTML)
        await bot.send_video(chat_id=settings.ADMIN_ID, video=message.video.file_id)
        return True

    await answer_msg(message, translate(MessageText.invalid_content, profile.language))
    return False


def chunk_message(text: str, *, template: str, sender_name: str) -> Iterable[str]:
    base_render = template.format(name=sender_name, message="")
    overhead = len(base_render)
    allowance = 3900 - overhead
    if allowance <= 0:
        allowance = max(3900 // 2, 512)
    if len(text) <= allowance:
        yield text
        return
    for start in range(0, len(text), allowance):
        yield text[start : start + allowance]
