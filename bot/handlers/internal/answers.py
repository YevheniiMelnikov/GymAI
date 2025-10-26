import html
from typing import Iterable

from aiohttp import web
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from loguru import logger
from pydantic import ValidationError

from bot.handlers.internal.auth import require_internal_auth
from bot.handlers.internal.schemas import AiAnswerNotify
from bot.states import States
from bot.texts.text_manager import msg_text
from config.app_settings import settings
from core.ai_coach.state.ask_ai import AiQuestionState
from core.exceptions import ClientNotFoundError
from core.services import APIService
from core.schemas import Profile

from .tasks import _resolve_client_and_profile


def _chunk_message(text: str, limit: int = 3500) -> Iterable[str]:
    for start in range(0, len(text), limit):
        yield text[start : start + limit]


@require_internal_auth
async def internal_ai_answer_ready(request: web.Request) -> web.Response:
    try:
        payload_raw = await request.json()
    except Exception:
        return web.json_response({"detail": "Invalid JSON"}, status=400)

    try:
        payload = AiAnswerNotify.model_validate(payload_raw)
    except ValidationError as exc:
        return web.json_response({"detail": exc.errors()}, status=400)

    state_tracker = AiQuestionState.create()
    if not await state_tracker.claim_delivery(payload.request_id):
        logger.debug(f"event=ask_ai_answer_duplicate request_id={payload.request_id} client_id={payload.client_id}")
        return web.json_response({"result": "ignored"}, status=202)

    try:
        client, profile_id, client_profile_id = await _resolve_client_and_profile(
            payload.client_id, payload.client_profile_id
        )
    except ClientNotFoundError:
        await state_tracker.mark_failed(payload.request_id, "client_not_found")
        logger.error(
            f"event=ask_ai_answer_client_missing request_id={payload.request_id} client_id={payload.client_id}"
        )
        return web.json_response({"detail": "client_not_found"}, status=404)

    profile: Profile | None = await APIService.profile.get_profile(profile_id)
    if profile is None:
        await state_tracker.mark_failed(payload.request_id, "profile_not_found")
        logger.error(f"event=ask_ai_answer_profile_missing request_id={payload.request_id} profile_id={profile_id}")
        return web.json_response({"detail": "profile_not_found"}, status=404)

    bot: Bot = request.app["bot"]
    dispatcher = request.app.get("dp")
    if dispatcher is not None:
        storage = dispatcher.storage
        state_key = StorageKey(bot_id=bot.id, chat_id=profile.tg_id, user_id=profile.tg_id)
        fsm = FSMContext(storage=storage, key=state_key)
        state_data = await fsm.get_data()
        state_data.update(
            {
                "profile": profile.model_dump(),
                "client": client.model_dump(),
                "last_request_id": payload.request_id,
            }
        )
        for temporary_key in ("ask_ai_prompt_id", "ask_ai_prompt_chat_id", "ask_ai_cost"):
            state_data.pop(temporary_key, None)
        await fsm.set_data(state_data)

        current_state = await fsm.get_state()
        if current_state == States.ask_ai_question.state:
            await fsm.set_state(States.select_service)

    language = profile.language
    request_id = payload.request_id

    if payload.status != "success":
        reason = payload.error or "unknown_error"
        await state_tracker.mark_failed(request_id, reason)
        error_message = msg_text("coach_agent_error", language).format(tg=settings.TG_SUPPORT_CONTACT)
        try:
            await bot.send_message(chat_id=profile.tg_id, text=error_message)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                f"event=ask_ai_error_message_failed request_id={request_id} profile_id={profile.id} error={exc!s}"
            )
        return web.json_response({"result": "error"}, status=202)

    answer_text = (payload.answer or "").strip()
    if not answer_text:
        await state_tracker.mark_failed(request_id, "empty_answer")
        logger.warning(
            "event=ask_ai_answer_empty request_id={} client_id={} placeholder_blocked={}",
            request_id,
            payload.client_id,
            settings.DISABLE_MANUAL_PLACEHOLDER,
        )
        if not settings.DISABLE_MANUAL_PLACEHOLDER:
            fallback = msg_text("coach_agent_error", language).format(tg=settings.TG_SUPPORT_CONTACT)
            try:
                await bot.send_message(chat_id=profile.tg_id, text=fallback)
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
            "event=ask_ai_answer_sources request_id={} client_id={} count={} sources={}",
            request_id,
            payload.client_id,
            len(payload.sources),
            " | ".join(payload.sources),
        )

    escaped_answer = html.escape(answer_text)
    message_text = msg_text("ask_ai_answer", language).format(answer=escaped_answer)
    chunks = list(_chunk_message(message_text))
    rendered_len = sum(len(chunk) for chunk in chunks)
    truncated = "yes" if len(chunks) > 1 else "no"
    logger.info(
        "bot.send out_len={} rendered_len={} truncated={}",
        len(answer_text),
        rendered_len,
        truncated,
    )

    try:
        for chunk in chunks:
            await bot.send_message(
                chat_id=profile.tg_id,
                text=chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
    except Exception as exc:  # noqa: BLE001
        await state_tracker.mark_failed(request_id, f"send_failed:{exc!s}")
        logger.error(f"event=ask_ai_answer_send_failed request_id={request_id} profile_id={profile.id} error={exc!s}")
        return web.json_response({"detail": "send_failed"}, status=500)

    await state_tracker.mark_delivered(request_id)
    logger.info(
        f"event=ask_ai_answer_delivered request_id={request_id} client_id={payload.client_id} profile_id={profile.id}"
    )
    return web.json_response({"result": "ok"})
