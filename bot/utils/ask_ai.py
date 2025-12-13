"""Utilities for preparing Ask AI requests and prompting users."""

from base64 import b64encode
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.types.input_file import FSInputFile
from loguru import logger

from bot.keyboards import ask_ai_prompt_kb
from bot.texts import MessageText, translate
from bot.states import States
from bot.utils.bot import answer_msg, del_msg
from bot.utils.credits import available_ai_services
from bot.utils.media import download_limited_file, get_ai_qa_image_limit
from bot.utils.menus import prompt_profile_completion_questionnaire, show_balance_menu
from config.app_settings import settings
from bot.utils.profiles import fetch_user
from core.ai_coach.models import AskAiPreparationResult
from core.cache import Cache
from core.enums import ProfileStatus
from core.exceptions import AskAiPreparationError, ProfileNotFoundError
from core.schemas import Profile


async def prepare_ask_ai_request(
    *,
    message: Message,
    profile: Profile,
    state_data: dict[str, Any],
    bot: Bot,
) -> AskAiPreparationResult:
    profile_data = state_data.get("profile")
    if profile_data is None:
        try:
            user_profile = await Cache.profile.get_record(profile.id)
        except ProfileNotFoundError as exc:
            raise AskAiPreparationError("unexpected_error") from exc
    else:
        user_profile = Profile.model_validate(profile_data)

    prompt_raw = (message.text or message.caption or "").strip()
    if not prompt_raw:
        raise AskAiPreparationError("invalid_content")

    services = {service.name: service.credits for service in available_ai_services()}
    default_cost = int(settings.ASK_AI_PRICE)
    cost_hint = state_data.get("ask_ai_cost")
    cost = int(cost_hint or services.get("ask_ai", default_cost))

    if user_profile.credits < cost:
        raise AskAiPreparationError("not_enough_credits")

    image_base64: str | None = None
    image_mime: str | None = None
    limit_bytes = get_ai_qa_image_limit()

    if message.photo:
        photo = message.photo[-1]
        file_bytes, size_hint = await download_limited_file(bot, photo.file_id)
        if file_bytes is None:
            if size_hint and size_hint > limit_bytes:
                raise AskAiPreparationError("image_error")
            raise AskAiPreparationError("unexpected_error")
        image_base64 = b64encode(file_bytes).decode("ascii")
        image_mime = "image/jpeg"
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        document = message.document
        file_bytes, size_hint = await download_limited_file(bot, document.file_id)
        if file_bytes is None:
            if size_hint and size_hint > limit_bytes:
                raise AskAiPreparationError("image_error")
            raise AskAiPreparationError("unexpected_error")
        image_base64 = b64encode(file_bytes).decode("ascii")
        image_mime = document.mime_type

    return AskAiPreparationResult(
        profile=user_profile,
        prompt=prompt_raw,
        cost=cost,
        image_base64=image_base64,
        image_mime=image_mime,
    )


async def _notify_user(
    origin: Message | CallbackQuery,
    text: str,
    *,
    show_alert: bool = False,
) -> None:
    if isinstance(origin, CallbackQuery):
        await origin.answer(text, show_alert=show_alert)
    else:
        await answer_msg(origin, text)


async def start_ask_ai_prompt(
    origin: Message | CallbackQuery,
    profile: Profile,
    state: FSMContext,
    *,
    delete_origin: bool,
    show_balance_menu_on_insufficient: bool,
) -> bool:
    """Display Ask AI prompt if user has enough credits."""
    lang = profile.language or settings.DEFAULT_LANG
    try:
        user_profile = await fetch_user(profile, refresh_if_incomplete=True)
    except (ProfileNotFoundError, ValueError):
        await _notify_user(origin, translate(MessageText.unexpected_error, lang), show_alert=True)
        return False

    if user_profile.status != ProfileStatus.completed:
        await prompt_profile_completion_questionnaire(
            origin,
            profile,
            state,
            language=lang,
            pending_flow={"name": "ask_ai_prompt"},
        )
        if delete_origin:
            await del_msg(origin)
        return False

    services = {service.name: service.credits for service in available_ai_services()}
    cost = int(services.get("ask_ai", int(settings.ASK_AI_PRICE)))
    if user_profile.credits < cost:
        await _notify_user(origin, translate(MessageText.not_enough_credits, lang), show_alert=True)
        if show_balance_menu_on_insufficient:
            await show_balance_menu(origin, profile, state, already_answered=True)
        return False

    file_path = Path(__file__).resolve().parent.parent / "images" / "ai_coach.png"
    keyboard = ask_ai_prompt_kb(lang)
    await state.set_state(States.ask_ai_question)
    prompt_text = translate(MessageText.ask_ai_prompt, lang).format(
        cost=cost,
        balance=user_profile.credits,
        bot_name=settings.BOT_NAME,
    )
    update_payload: dict[str, object] = {
        "profile": user_profile.model_dump(),
        "ask_ai_cost": cost,
    }
    if file_path.exists():
        prompt_message = await answer_msg(
            origin,
            caption=prompt_text,
            photo=FSInputFile(file_path),
            reply_markup=keyboard,
        )
    else:
        logger.warning(f"event=ask_ai_prompt_image_missing path={file_path} profile_id={user_profile.id}")
        prompt_message = await answer_msg(
            origin,
            prompt_text,
            reply_markup=keyboard,
        )
    if prompt_message is not None:
        update_payload["ask_ai_prompt_id"] = prompt_message.message_id
        update_payload["ask_ai_prompt_chat_id"] = prompt_message.chat.id
    await state.update_data(**update_payload)  # pyrefly: ignore[bad-argument-type]
    if delete_origin:
        await del_msg(origin)
    return True
