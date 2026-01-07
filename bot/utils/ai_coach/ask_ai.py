import io
from base64 import b64encode
from pathlib import Path
from typing import Any, cast

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, FSInputFile
from celery import chain
from celery.result import AsyncResult
from loguru import logger
from pydantic import ValidationError

from bot.keyboards import ask_ai_prompt_kb
from bot.texts import MessageText, translate
from bot.states import States
from bot.utils.bot import answer_msg, del_msg
from bot.pricing import ServiceCatalog
from bot.utils.menus import prompt_profile_completion_questionnaire, show_balance_menu
from config.app_settings import settings
from bot.utils.profiles import fetch_user
from core.ai_coach import AiQuestionPayload, AiAttachmentPayload
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

    default_cost = int(settings.ASK_AI_PRICE)
    cost_hint = state_data.get("ask_ai_cost")
    cost = int(cost_hint or ServiceCatalog.service_price("ask_ai") or default_cost)

    if user_profile.credits < cost:
        raise AskAiPreparationError("not_enough_credits")

    image_base64: str | None = None
    image_mime: str | None = None
    limit_bytes = int(settings.AI_QA_IMAGE_MAX_BYTES)

    if message.photo:
        photo = message.photo[-1]
        file_bytes, size_hint = await _download_limited_file(bot, photo.file_id)
        if file_bytes is None:
            if size_hint and size_hint > limit_bytes:
                raise AskAiPreparationError("image_error")
            raise AskAiPreparationError("unexpected_error")
        image_base64 = b64encode(file_bytes).decode("ascii")
        image_mime = "image/jpeg"
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        document = message.document
        file_bytes, size_hint = await _download_limited_file(bot, document.file_id)
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

    cost = int(ServiceCatalog.service_price("ask_ai") or settings.ASK_AI_PRICE)
    if user_profile.credits < cost:
        await _notify_user(origin, translate(MessageText.not_enough_credits, lang), show_alert=True)
        if show_balance_menu_on_insufficient:
            await show_balance_menu(origin, profile, state, already_answered=True)
        return False

    file_path = Path(__file__).resolve().parent.parent.parent / "images" / "ai_coach.png"
    keyboard = ask_ai_prompt_kb(lang)
    await state.set_state(States.ask_ai_question)
    prompt_text = translate(MessageText.ask_ai_prompt, lang).format(
        cost=cost,
        balance=user_profile.credits,
        bot_name=settings.BOT_NAME,
    )
    update_payload: dict[str, object] = {
        "profile": user_profile.model_dump(mode="json"),
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


def reply_target_missing(exc: TelegramBadRequest) -> bool:
    text = str(getattr(exc, "message", "") or "")
    if not text and exc.args:
        first_arg = exc.args[0]
        if isinstance(first_arg, str):
            text = first_arg
    lowered = text.lower()
    return (
        "reply message not found" in lowered
        or "message to reply not found" in lowered
        or "replied message not found" in lowered
    )


def extract_error_text(exc: TelegramBadRequest) -> str:
    text = str(getattr(exc, "message", "") or "")
    if not text and exc.args:
        for arg in exc.args:
            if isinstance(arg, str):
                text = arg
                break
    return text


async def send_chunk_with_reply_fallback(
    *,
    bot: Bot,
    chat_id: int,
    text: str,
    parse_mode: ParseMode,
    reply_markup: Any | None,
    reply_to_message_id: int | None,
) -> int | None:
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
        )
        return reply_to_message_id
    except TelegramBadRequest as exc:
        if reply_to_message_id is not None:
            error_text = extract_error_text(exc)
            if reply_target_missing(exc):
                logger.warning(
                    "event=ask_ai_reply_target_missing chat_id={} detail={}",
                    chat_id,
                    error_text,
                )
            else:
                logger.warning(
                    "event=ask_ai_reply_send_failed chat_id={} detail={}",
                    chat_id,
                    error_text,
                )
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
                reply_to_message_id=None,
                reply_markup=reply_markup,
            )
            return None
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "event=ask_ai_reply_unexpected_failure chat_id={} reply_to={} error={}",
            chat_id,
            reply_to_message_id,
            exc,
        )
        raise


def _build_ai_question_payload(
    *,
    profile_id: int,
    language: str,
    prompt: str,
    request_id: str,
    cost: int,
    image_base64: str | None,
    image_mime: str | None,
) -> AiQuestionPayload | None:
    attachments: list[AiAttachmentPayload] = []
    if image_base64 and image_mime:
        attachments.append(AiAttachmentPayload(mime=image_mime, data_base64=image_base64))

    try:
        return AiQuestionPayload(
            profile_id=profile_id,
            language=language,
            prompt=prompt,
            attachments=attachments,
            request_id=request_id,
            cost=cost,
        )
    except ValidationError as exc:
        logger.error(f"event=ask_ai_invalid_payload request_id={request_id} profile_id={profile_id} error={exc!s}")
        return None


def _dispatch_ai_question_task(
    *,
    payload_model: AiQuestionPayload,
    request_id: str,
    profile_id: int,
) -> str | None:
    try:
        from core.tasks.ai_coach import (  # Local import to avoid circular dependency
            ask_ai_question,
            handle_ai_question_failure,
            notify_ai_answer_ready_task,
        )
    except Exception as exc:  # pragma: no cover - import failure
        logger.error(f"event=ask_ai_task_import_failed request_id={request_id} error={exc!s}")
        return None

    payload = payload_model.model_dump(mode="json")
    headers = {
        "request_id": request_id,
        "profile_id": profile_id,
        "action": "ask_ai",
    }
    options = {"queue": "ai_coach", "routing_key": "ai_coach", "headers": headers}

    ask_sig = ask_ai_question.s(payload).set(**options)  # pyrefly: ignore[not-callable]
    notify_sig = notify_ai_answer_ready_task.s().set(  # pyrefly: ignore[not-callable]
        queue="ai_coach", routing_key="ai_coach", headers=headers
    )
    failure_sig = handle_ai_question_failure.s(payload).set(  # pyrefly: ignore[not-callable]
        queue="ai_coach", routing_key="ai_coach"
    )

    try:
        async_result = cast(AsyncResult, chain(ask_sig, notify_sig).apply_async(link_error=[failure_sig]))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"event=ask_ai_dispatch_failed request_id={request_id} profile_id={profile_id} error={exc!s}")
        return None

    task_id = cast(str | None, getattr(async_result, "id", None))
    if task_id is None:
        logger.error(f"event=ask_ai_missing_task_id request_id={request_id} profile_id={profile_id}")
        return None
    logger.info(f"event=ask_ai_enqueued request_id={request_id} task_id={task_id} profile_id={profile_id}")
    return task_id


async def enqueue_ai_question(
    *,
    profile: Profile,
    prompt: str,
    language: str,
    request_id: str,
    cost: int,
    image_base64: str | None = None,
    image_mime: str | None = None,
) -> bool:
    profile_id = profile.id
    if profile_id <= 0:
        logger.error(f"event=ask_ai_invalid_profile request_id={request_id} profile_id={profile_id}")
        return False

    payload_model = _build_ai_question_payload(
        profile_id=profile_id,
        language=language,
        prompt=prompt,
        request_id=request_id,
        cost=cost,
        image_base64=image_base64,
        image_mime=image_mime,
    )
    if payload_model is None:
        return False

    task_id = _dispatch_ai_question_task(
        payload_model=payload_model,
        request_id=request_id,
        profile_id=profile_id,
    )
    return task_id is not None


async def _download_limited_file(
    bot: Bot, file_id: str, *, max_bytes: int | None = None
) -> tuple[bytes | None, int | None]:
    """Download a Telegram file if it fits within the configured byte limit."""

    limit = max_bytes or int(settings.AI_QA_IMAGE_MAX_BYTES)
    try:
        file = await bot.get_file(file_id)
    except TelegramBadRequest as exc:
        logger.warning(f"event=ask_ai_get_file_failed file_id={file_id} error={exc}")
        return None, None

    size_hint = getattr(file, "file_size", None)
    if size_hint and size_hint > limit:
        logger.info(
            "event=ask_ai_attachment_rejected reason=size_hint file_id={} size={} limit={}",
            file_id,
            size_hint,
            limit,
        )
        return None, size_hint

    buffer = io.BytesIO()
    file_path = getattr(file, "file_path", None)
    if file_path is None:
        logger.warning(f"event=ask_ai_download_missing_path file_id={file_id}")
        return None, size_hint

    try:
        await bot.download_file(file_path, buffer)
    except TelegramBadRequest as exc:
        logger.warning(f"event=ask_ai_download_failed file_id={file_id} error={exc}")
        return None, size_hint

    data = buffer.getvalue()
    if len(data) > limit:
        logger.info(
            "event=ask_ai_attachment_rejected reason=download_size file_id={} size={} limit={}",
            file_id,
            len(data),
            limit,
        )
        return None, len(data)

    return data, size_hint or len(data)
