from aiohttp import web
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from loguru import logger
from pydantic import ValidationError

from bot.handlers.internal.auth import require_internal_auth
from bot.handlers.internal.schemas import AiDietNotify
from bot.states import States
from bot.texts import MessageText, translate
from bot.utils.ask_ai_messages import chunk_formatted_message, send_chunk_with_reply_fallback
from bot.utils.diet_plans import format_diet_plan
from bot.keyboards import diet_result_kb
from config.app_settings import settings
from core.ai_coach.state.diet import AiDietState
from core.exceptions import ProfileNotFoundError

from .tasks import _resolve_profile


@require_internal_auth
async def internal_ai_diet_ready(request: web.Request) -> web.Response:
    try:
        return await _internal_ai_diet_ready_impl(request)
    except Exception as exc:  # noqa: BLE001
        logger.exception("event=ai_diet_webhook_failed error={}", exc)
        return web.json_response({"detail": "internal_error"}, status=500)


async def _internal_ai_diet_ready_impl(request: web.Request) -> web.Response:
    try:
        payload_raw = await request.json()
    except Exception:
        return web.json_response({"detail": "Invalid JSON"}, status=400)

    try:
        payload = AiDietNotify.model_validate(payload_raw)
    except ValidationError as exc:
        return web.json_response({"detail": exc.errors()}, status=400)

    logger.info(
        "event=ai_diet_webhook request_id={} profile_id={} status={} force={}",
        payload.request_id,
        payload.profile_id,
        payload.status,
        payload.force,
    )

    state_tracker = AiDietState.create()
    request_id = payload.request_id
    force_delivery = bool(payload.force)
    already_delivered = await state_tracker.is_delivered(request_id)
    already_failed = await state_tracker.is_failed(request_id)
    if already_delivered or (already_failed and not force_delivery):
        logger.debug(
            f"event=ai_diet_duplicate request_id={request_id} profile_id={payload.profile_id} force={force_delivery}"
        )
        return web.json_response({"result": "ignored"}, status=202)

    try:
        profile = await _resolve_profile(payload.profile_id, None)
    except ProfileNotFoundError:
        await state_tracker.mark_failed(payload.request_id, "profile_not_found")
        logger.error(f"event=ai_diet_profile_missing request_id={payload.request_id} profile_id={payload.profile_id}")
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
                "last_request_id": payload.request_id,
            }
        )
        await fsm.set_data(state_data)
        if await fsm.get_state() == States.diet_confirm_service.state:
            await fsm.set_state(States.main_menu)

    language = profile.language

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
                reply_to_message_id=None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "event=ai_diet_error_message_failed request_id={} profile_id={} error={}",
                request_id,
                profile.id,
                exc,
            )
        return web.json_response({"result": "error"}, status=202)

    if payload.plan is None:
        await state_tracker.mark_failed(request_id, "empty_plan")
        logger.error("event=ai_diet_empty_plan request_id={} profile_id={}", request_id, payload.profile_id)
        return web.json_response({"detail": "empty_plan"}, status=400)

    incoming_template = translate(MessageText.diet_response_template, language)
    rendered_body = format_diet_plan(payload.plan, language)
    chunks = chunk_formatted_message(rendered_body, template=incoming_template, sender_name=settings.BOT_NAME)
    menu = diet_result_kb(language)

    try:
        for idx, chunk in enumerate(chunks):
            message_text = incoming_template.format(name=settings.BOT_NAME, message=chunk)
            reply_markup = menu if idx == len(chunks) - 1 else None
            await send_chunk_with_reply_fallback(
                bot=bot,
                chat_id=profile.tg_id,
                text=message_text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                reply_to_message_id=None,
            )
    except Exception as exc:  # noqa: BLE001
        await state_tracker.mark_failed(request_id, f"send_failed:{exc!s}")
        logger.exception(
            "event=ai_diet_send_failed request_id={} profile_id={} error={}",
            request_id,
            profile.id,
            exc,
        )
        return web.json_response({"detail": "send_failed"}, status=202)

    await state_tracker.mark_delivered(request_id)
    logger.info(f"event=ai_diet_delivered request_id={request_id} profile_id={payload.profile_id}")
    return web.json_response({"result": "ok"})
