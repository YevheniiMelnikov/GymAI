from aiohttp import web
from aiogram import Bot
from aiogram.enums import ParseMode
from loguru import logger
from pydantic import ValidationError

from bot.handlers.internal.auth import require_internal_auth
from bot.handlers.internal.schemas import AiDietNotify
from bot.keyboards import diet_view_kb
from bot.texts import MessageText, translate
from bot.utils.ai_coach.ask_ai import send_chunk_with_reply_fallback
from bot.utils.urls import get_webapp_url, support_contact_url
from config.app_settings import settings
from core.ai_coach.state.diet import AiDietState
from core.exceptions import ProfileNotFoundError, UserServiceError
from core.services import APIService
from .tasks import _resolve_profile


@require_internal_auth
async def internal_ai_diet_ready(request: web.Request) -> web.Response:
    try:
        return await _internal_ai_diet_ready_impl(request)
    except Exception as exc:  # noqa: BLE001
        logger.exception("event=ai_diet_webhook_failed error={}", exc)
        return web.json_response({"detail": "internal_error"}, status=500)


async def _internal_ai_diet_ready_impl(request: web.Request) -> web.Response:  # noqa: C901
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
        logger.error(f"event=ai_diet_profile_missing request_id={request_id} profile_id={payload.profile_id}")
        return web.json_response({"detail": "profile_not_found"}, status=404)

    bot: Bot = request.app["bot"]

    language = profile.language

    if payload.status != "success":
        reason = payload.error or "unknown_error"
        await state_tracker.mark_failed(request_id, reason)
        error_message = translate(MessageText.coach_agent_error, language).format(tg=support_contact_url())
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

    diet_id = None
    try:
        diet_id = await APIService.diet.save_plan(
            profile_id=payload.profile_id,
            request_id=request_id,
            plan=payload.plan.model_dump(mode="json"),
        )
        if diet_id is None:
            raise UserServiceError("save_plan returned None")
    except UserServiceError as e:
        await state_tracker.mark_failed(request_id, f"save_failed:{e!s}")
        logger.error(f"event=ai_diet_save_failed request_id={request_id} error={e}")
        try:
            await send_chunk_with_reply_fallback(
                bot=bot,
                chat_id=profile.tg_id,
                text=translate(MessageText.coach_agent_error, language).format(tg=support_contact_url()),
                parse_mode=ParseMode.HTML,
                reply_markup=None,
                reply_to_message_id=None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"event=ai_diet_save_failed_notify_failed request_id={request_id} error={exc}")
        return web.json_response({"detail": "save_failed"}, status=202)

    logger.info(f"event=ai_diet_save_success request_id={request_id} diet_id={diet_id}")

    webapp_url = get_webapp_url("diets", language, extra_params={"diet_id": str(diet_id)})
    menu = diet_view_kb(language, webapp_url) if webapp_url else None

    try:
        await bot.send_message(
            chat_id=profile.tg_id,
            text=translate(MessageText.diet_ready, language).format(bot_name=settings.BOT_NAME),
            parse_mode=ParseMode.HTML,
            reply_markup=menu,
            disable_notification=True,
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
