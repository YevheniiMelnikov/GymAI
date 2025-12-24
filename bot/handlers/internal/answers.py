from aiohttp import web
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from loguru import logger
from pydantic import ValidationError

from bot.handlers.internal.auth import require_internal_auth
from bot.handlers.internal.schemas import AiAnswerNotify
from bot.keyboards import ask_ai_again_kb
from bot.states import States
from bot.texts import MessageText, translate
from bot.utils.ask_ai_messages import (
    chunk_formatted_message,
    format_answer_blocks,
    format_plain_answer,
    send_chunk_with_reply_fallback,
)
from config.app_settings import settings
from core.ai_coach.state.ask_ai import AiQuestionState
from core.exceptions import ProfileNotFoundError

from .tasks import _resolve_profile


@require_internal_auth
async def internal_ai_answer_ready(request: web.Request) -> web.Response:
    try:
        return await _internal_ai_answer_ready_impl(request)
    except Exception as exc:  # noqa: BLE001
        logger.exception("event=ask_ai_answer_webhook_failed error={}", exc)
        return web.json_response({"detail": "internal_error"}, status=500)


async def _internal_ai_answer_ready_impl(request: web.Request) -> web.Response:
    try:
        payload_raw = await request.json()
    except Exception:
        return web.json_response({"detail": "Invalid JSON"}, status=400)

    try:
        payload = AiAnswerNotify.model_validate(payload_raw)
    except ValidationError as exc:
        return web.json_response({"detail": exc.errors()}, status=400)

    logger.info(
        "event=ask_ai_answer_webhook request_id={} profile_id={} status={} force={}",
        payload.request_id,
        payload.profile_id,
        payload.status,
        payload.force,
    )

    state_tracker = AiQuestionState.create()
    request_id = payload.request_id
    force_delivery = bool(payload.force)
    already_delivered = await state_tracker.is_delivered(request_id)
    already_failed = await state_tracker.is_failed(request_id)
    if already_delivered or (already_failed and not force_delivery):
        logger.debug(
            f"event=ask_ai_answer_duplicate request_id={request_id} profile_id={payload.profile_id} "
            f"force={force_delivery}"
        )
        return web.json_response({"result": "ignored"}, status=202)

    try:
        profile = await _resolve_profile(payload.profile_id, None)
    except ProfileNotFoundError:
        await state_tracker.mark_failed(payload.request_id, "profile_not_found")
        logger.error(
            f"event=ask_ai_answer_client_missing request_id={payload.request_id} profile_id={payload.profile_id}"
        )
        return web.json_response({"detail": "profile_not_found"}, status=404)

    bot: Bot = request.app["bot"]
    dispatcher = request.app.get("dp")
    reply_to_message_id: int | None = None
    if dispatcher is not None:
        storage = dispatcher.storage
        state_key = StorageKey(bot_id=bot.id, chat_id=profile.tg_id, user_id=profile.tg_id)
        fsm = FSMContext(storage=storage, key=state_key)
        state_data = await fsm.get_data()
        reply_to_message_id = state_data.get("ask_ai_question_message_id")
        state_data.update(
            {
                "profile": profile.model_dump(mode="json"),
                "last_request_id": payload.request_id,
            }
        )
        for temporary_key in ("ask_ai_prompt_id", "ask_ai_prompt_chat_id", "ask_ai_cost", "ask_ai_question_message_id"):
            state_data.pop(temporary_key, None)
        await fsm.set_data(state_data)

        current_state = await fsm.get_state()
        if current_state == States.ask_ai_question.state:
            await fsm.set_state(States.main_menu)

    language = profile.language
    request_id = payload.request_id

    if payload.status != "success":
        reason = payload.error or "unknown_error"
        await state_tracker.mark_failed(request_id, reason)
        error_message = translate(MessageText.coach_agent_error, language).format(tg=settings.TG_SUPPORT_CONTACT)
        try:
            await send_chunk_with_reply_fallback(
                bot=bot,
                chat_id=profile.tg_id,
                text=error_message,
                parse_mode=ParseMode.HTML,
                reply_markup=None,
                reply_to_message_id=reply_to_message_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                f"event=ask_ai_error_message_failed request_id={request_id} profile_id={profile.id} error={exc!s}"
            )
        return web.json_response({"result": "error"}, status=202)

    answer_text = (payload.answer or "").strip()
    if not answer_text:
        await state_tracker.mark_failed(request_id, "empty_answer")
        logger.warning(
            "event=ask_ai_answer_empty request_id={} profile_id={} placeholder_blocked={}",
            request_id,
            payload.profile_id,
            settings.DISABLE_MANUAL_PLACEHOLDER,
        )
        if not settings.DISABLE_MANUAL_PLACEHOLDER:
            fallback = translate(MessageText.coach_agent_error, language).format(tg=settings.TG_SUPPORT_CONTACT)
            try:
                await send_chunk_with_reply_fallback(
                    bot=bot,
                    chat_id=profile.tg_id,
                    text=fallback,
                    parse_mode=ParseMode.HTML,
                    reply_markup=None,
                    reply_to_message_id=reply_to_message_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "event=ask_ai_empty_error_message_failed request_id={} profile_id={} error={}",
                    request_id,
                    profile.id,
                    exc,
                )
        return web.json_response({"detail": "empty_answer"}, status=400)

    if payload.sources:
        logger.info(
            "event=ask_ai_answer_sources request_id={} profile_id={} count={}",
            request_id,
            payload.profile_id,
            len(payload.sources),
        )
        if settings.AI_COACH_LOG_PAYLOADS:
            logger.debug(
                "event=ask_ai_answer_sources_payload request_id={} profile_id={} sources={}",
                request_id,
                payload.profile_id,
                " | ".join(payload.sources),
            )

    incoming_template = translate(MessageText.ask_ai_response_template, language)
    rendered_body = format_answer_blocks(payload.blocks) if payload.blocks else format_plain_answer(answer_text)
    chunks = chunk_formatted_message(rendered_body, template=incoming_template, sender_name=settings.BOT_NAME)
    rendered_len = sum(len(incoming_template.format(name=settings.BOT_NAME, message=chunk)) for chunk in chunks)
    truncated = "yes" if len(chunks) > 1 else "no"
    logger.info(
        "bot.send out_len={} rendered_len={} truncated={}",
        len(answer_text),
        rendered_len,
        truncated,
    )

    try:
        ask_again_keyboard = ask_ai_again_kb(language)
        current_reply_id = reply_to_message_id
        for index, chunk in enumerate(chunks):
            message_text = incoming_template.format(name=settings.BOT_NAME, message=chunk)
            reply_markup = ask_again_keyboard if index == len(chunks) - 1 else None
            current_reply_id = await send_chunk_with_reply_fallback(
                bot=bot,
                chat_id=profile.tg_id,
                text=message_text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                reply_to_message_id=current_reply_id,
            )
    except Exception as exc:  # noqa: BLE001
        await state_tracker.mark_failed(request_id, f"send_failed:{exc!s}")
        logger.exception(
            "event=ask_ai_answer_send_failed request_id={} profile_id={} error={}",
            request_id,
            profile.id,
            exc,
        )
        return web.json_response({"detail": "send_failed"}, status=202)

    await state_tracker.mark_delivered(request_id)
    logger.info(f"event=ask_ai_answer_delivered request_id={request_id} profile_id={payload.profile_id}")
    return web.json_response({"result": "ok"})
