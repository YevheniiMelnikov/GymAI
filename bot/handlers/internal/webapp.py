from typing import Any, cast

from aiohttp import web
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from loguru import logger

from bot.handlers.internal.auth import require_internal_auth
from bot.utils.bot import BotMessageProxy
from bot.utils.menus import (
    prompt_profile_completion_questionnaire,
    start_program_flow,
    start_subscription_flow,
)
from config.app_settings import settings
from core.cache import Cache
from core.enums import ProfileStatus
from core.exceptions import ProfileNotFoundError
from core.schemas import Profile
from core.services import APIService

ALLOWED_ACTIONS: set[str] = {"create_program", "create_subscription"}


async def _load_profile(profile_id: int, *, fallback_payload: dict[str, Any] | None = None) -> Profile | None:
    if fallback_payload:
        try:
            profile = Profile.model_validate(fallback_payload)
            await Cache.profile.save_record(profile.id, profile.model_dump(mode="json"))
            return profile
        except Exception:
            logger.warning(f"webapp_workout_profile_payload_invalid profile_id={profile_id}")
    try:
        return await Cache.profile.get_record(profile_id)
    except ProfileNotFoundError:
        pass
    profile = await APIService.profile.get_profile(profile_id)
    if profile is not None:
        await Cache.profile.save_record(profile.id, profile.model_dump(mode="json"))
    return profile


@require_internal_auth
async def internal_webapp_workout_action(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"detail": "bad_request"}, status=400)

    action_raw = payload.get("action")
    action = str(action_raw or "")
    if action not in ALLOWED_ACTIONS:
        return web.json_response({"detail": "bad_request"}, status=400)

    try:
        profile_id = int(payload.get("profile_id"))
        telegram_id = int(payload.get("telegram_id"))
    except (TypeError, ValueError):
        return web.json_response({"detail": "bad_request"}, status=400)

    profile_payload_raw = payload.get("profile")
    profile_payload = profile_payload_raw if isinstance(profile_payload_raw, dict) else None
    logger.info(f"webapp_workout_action_received profile_id={profile_id} action={action}")

    profile = await _load_profile(profile_id, fallback_payload=profile_payload)
    if profile is None:
        logger.warning(f"webapp_workout_profile_missing profile_id={profile_id}")
        return web.json_response({"detail": "not_found"}, status=404)

    chat_id = telegram_id
    if profile.tg_id != telegram_id:
        logger.warning(
            f"webapp_workout_tg_mismatch profile_id={profile.id} payload_tg={telegram_id} profile_tg={profile.tg_id}"
        )
        chat_id = profile.tg_id

    dispatcher = request.app.get("dp")
    if dispatcher is None:
        logger.error("Dispatcher missing for webapp workout action")
        return web.json_response({"detail": "unavailable"}, status=503)

    bot: Bot = request.app["bot"]
    state_key = StorageKey(bot_id=bot.id, chat_id=chat_id, user_id=chat_id)
    state = FSMContext(storage=dispatcher.storage, key=state_key)
    await state.update_data(profile=profile.model_dump(mode="json"), chat_id=chat_id)

    target = BotMessageProxy(bot=bot, chat_id=chat_id)
    language = cast(str, profile.language or settings.DEFAULT_LANG)
    if profile.status != ProfileStatus.completed:
        pending_name = "start_program_flow" if action == "create_program" else "start_subscription_flow"
        await prompt_profile_completion_questionnaire(
            target,
            profile,
            state,
            chat_id=chat_id,
            language=language,
            pending_flow={"name": pending_name},
        )
        return web.json_response({"status": "ok"})

    if action == "create_program":
        await start_program_flow(target, profile, state)
    else:
        await start_subscription_flow(target, profile, state)

    return web.json_response({"status": "ok"})
