from typing import Any, cast

from aiohttp import web
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from loguru import logger

from bot.handlers.internal.auth import require_internal_auth
from bot.types.messaging import BotMessageProxy
from bot.texts import MessageText, translate
from bot.keyboards import main_menu_kb
from bot.utils.menus import prompt_profile_completion_questionnaire, show_balance_menu
from bot.utils.bot import answer_msg
from bot.utils.urls import get_webapp_url
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
        await prompt_profile_completion_questionnaire(
            target,
            profile,
            state,
            chat_id=chat_id,
            language=language,
        )
        alert_text = translate(MessageText.finish_registration, language)
        return web.json_response({"status": "ok", "profile_incomplete": True, "message": alert_text})

    logger.info(f"webapp_workout_action_deprecated profile_id={profile.id} action={action}")
    return web.json_response({"detail": "deprecated"}, status=410)


@require_internal_auth
async def internal_webapp_weekly_survey_submitted(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"detail": "bad_request"}, status=400)

    try:
        profile_id = int(payload.get("profile_id"))
        telegram_id = int(payload.get("telegram_id"))
    except (TypeError, ValueError):
        return web.json_response({"detail": "bad_request"}, status=400)

    profile_payload_raw = payload.get("profile")
    profile_payload = profile_payload_raw if isinstance(profile_payload_raw, dict) else None
    profile = await _load_profile(profile_id, fallback_payload=profile_payload)
    if profile is None:
        logger.warning(f"webapp_weekly_survey_profile_missing profile_id={profile_id}")
        return web.json_response({"detail": "not_found"}, status=404)

    chat_id = telegram_id
    if profile.tg_id != telegram_id:
        logger.warning(
            "webapp_weekly_survey_tg_mismatch "
            f"profile_id={profile.id} payload_tg={telegram_id} profile_tg={profile.tg_id}"
        )
        chat_id = profile.tg_id

    bot: Bot = request.app["bot"]
    language = cast(str, profile.language or settings.DEFAULT_LANG)
    await bot.send_message(chat_id=chat_id, text=translate(MessageText.weekly_survey_submitted, language))
    dispatcher = request.app.get("dp")
    if dispatcher is None:
        logger.error("Dispatcher missing for webapp weekly survey submitted")
        return web.json_response({"detail": "unavailable"}, status=503)
    state_key = StorageKey(bot_id=bot.id, chat_id=chat_id, user_id=chat_id)
    state = FSMContext(storage=dispatcher.storage, key=state_key)
    await state.clear()
    await state.update_data(profile=profile.model_dump(mode="json"))
    target = BotMessageProxy(bot=bot, chat_id=chat_id)
    webapp_url = get_webapp_url("program", language)
    profile_webapp_url = get_webapp_url("profile", language)
    faq_webapp_url = get_webapp_url("faq", language)
    menu = main_menu_kb(
        language,
        webapp_url=webapp_url,
        profile_webapp_url=profile_webapp_url,
        faq_webapp_url=faq_webapp_url,
    )
    await answer_msg(target, translate(MessageText.main_menu, language), reply_markup=menu)
    return web.json_response({"status": "ok"})


@require_internal_auth
async def internal_webapp_profile_balance(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"detail": "bad_request"}, status=400)

    try:
        profile_id = int(payload.get("profile_id"))
        telegram_id = int(payload.get("telegram_id"))
    except (TypeError, ValueError):
        return web.json_response({"detail": "bad_request"}, status=400)

    profile_payload_raw = payload.get("profile")
    profile_payload = profile_payload_raw if isinstance(profile_payload_raw, dict) else None
    profile = await _load_profile(profile_id, fallback_payload=profile_payload)
    if profile is None:
        logger.warning(f"webapp_balance_profile_missing profile_id={profile_id}")
        return web.json_response({"detail": "not_found"}, status=404)

    chat_id = telegram_id
    if profile.tg_id != telegram_id:
        logger.warning(
            f"webapp_balance_tg_mismatch profile_id={profile.id} payload_tg={telegram_id} profile_tg={profile.tg_id}"
        )
        chat_id = profile.tg_id

    dispatcher = request.app.get("dp")
    if dispatcher is None:
        logger.error("Dispatcher missing for webapp balance action")
        return web.json_response({"detail": "unavailable"}, status=503)

    bot: Bot = request.app["bot"]
    state_key = StorageKey(bot_id=bot.id, chat_id=chat_id, user_id=chat_id)
    state = FSMContext(storage=dispatcher.storage, key=state_key)
    await state.clear()
    await state.update_data(profile=profile.model_dump(mode="json"), chat_id=chat_id)

    target = BotMessageProxy(bot=bot, chat_id=chat_id)
    profile_webapp_url = get_webapp_url("profile", profile.language)
    await show_balance_menu(
        target,
        profile,
        state,
        already_answered=True,
        back_webapp_url=profile_webapp_url,
    )
    return web.json_response({"status": "ok"})


@require_internal_auth
async def internal_webapp_profile_deleted(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"detail": "bad_request"}, status=400)

    try:
        profile_id = int(payload.get("profile_id"))
        telegram_id = int(payload.get("telegram_id"))
    except (TypeError, ValueError):
        return web.json_response({"detail": "bad_request"}, status=400)

    profile_payload_raw = payload.get("profile")
    profile_payload = profile_payload_raw if isinstance(profile_payload_raw, dict) else None
    profile = await _load_profile(profile_id, fallback_payload=profile_payload)
    if profile is None:
        logger.warning(f"webapp_profile_delete_missing profile_id={profile_id}")
        return web.json_response({"detail": "not_found"}, status=404)

    chat_id = telegram_id
    if profile.tg_id != telegram_id:
        logger.warning(
            "webapp_profile_delete_tg_mismatch profile_id={} payload_tg={} profile_tg={}",
            profile.id,
            telegram_id,
            profile.tg_id,
        )
        chat_id = profile.tg_id

    dp = request.app.get("dp")
    if dp is None:
        logger.error("Dispatcher missing for webapp profile delete action")
        return web.json_response({"detail": "unavailable"}, status=503)

    bot: Bot = request.app["bot"]
    state_key = StorageKey(bot_id=bot.id, chat_id=chat_id, user_id=chat_id)
    state = FSMContext(storage=dp.storage, key=state_key)
    await state.clear()
    await state.update_data(profile=None)
    language = cast(str, profile.language or settings.DEFAULT_LANG)
    await bot.send_message(chat_id=chat_id, text=translate(MessageText.profile_deleted, language))
    return web.json_response({"status": "ok"})
