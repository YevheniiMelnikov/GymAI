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
from bot.texts import msg_text
from bot.states import States
from bot.utils.bot import answer_msg, del_msg
from bot.utils.credits import available_ai_services
from bot.utils.media import download_limited_file, get_ai_qa_image_limit
from bot.utils.menus import show_balance_menu
from config.app_settings import settings
from core.cache import Cache
from core.enums import ClientStatus
from core.ai_coach.models import AskAiPreparationResult
from core.exceptions import AskAiPreparationError, ClientNotFoundError
from core.schemas import Client, Profile


async def prepare_ask_ai_request(
    *,
    message: Message,
    profile: Profile,
    state_data: dict[str, Any],
    bot: Bot,
) -> AskAiPreparationResult:
    client_data = state_data.get("client")
    if client_data is None:
        try:
            client = await Cache.client.get_client(profile.id)
        except ClientNotFoundError as exc:
            raise AskAiPreparationError("unexpected_error") from exc
    else:
        client = Client.model_validate(client_data)

    prompt_raw = (message.text or message.caption or "").strip()
    if not prompt_raw:
        raise AskAiPreparationError("invalid_content")

    services = {service.name: service.credits for service in available_ai_services()}
    default_cost = int(settings.ASK_AI_PRICE)
    cost_hint = state_data.get("ask_ai_cost")
    cost = int(cost_hint or services.get("ask_ai", default_cost))

    if client.credits < cost:
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
        client=client,
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
        client = await Cache.client.get_client(profile.id)
    except ClientNotFoundError:
        await _notify_user(origin, msg_text("unexpected_error", lang), show_alert=True)
        return False

    if client.status == ClientStatus.initial:
        await _notify_user(origin, msg_text("finish_registration_to_get_credits", lang), show_alert=True)
        if delete_origin:
            await del_msg(origin)
        return False

    services = {service.name: service.credits for service in available_ai_services()}
    cost = int(services.get("ask_ai", int(settings.ASK_AI_PRICE)))
    if client.credits < cost:
        await _notify_user(origin, msg_text("not_enough_credits", lang), show_alert=True)
        if show_balance_menu_on_insufficient:
            await show_balance_menu(origin, profile, state)
        return False

    file_path = Path(__file__).resolve().parent.parent / "images" / "ai_coach.png"
    keyboard = ask_ai_prompt_kb(lang)
    await state.set_state(States.ask_ai_question)
    prompt_text = msg_text("ask_ai_prompt", lang).format(cost=cost, balance=client.credits)
    if file_path.exists():
        prompt_message = await answer_msg(
            origin,
            caption=prompt_text,
            photo=FSInputFile(file_path),
            reply_markup=keyboard,
        )
    else:
        logger.warning(f"event=ask_ai_prompt_image_missing path={file_path} client_id={client.id}")
        prompt_message = await answer_msg(
            origin,
            prompt_text,
            reply_markup=keyboard,
        )
    update_payload: dict[str, object] = {
        "client": client.model_dump(),
        "ask_ai_cost": cost,
    }
    if prompt_message is not None:
        update_payload["ask_ai_prompt_id"] = prompt_message.message_id
        update_payload["ask_ai_prompt_chat_id"] = prompt_message.chat.id
    await state.update_data(**update_payload)
    if delete_origin:
        await del_msg(origin)
    return True
