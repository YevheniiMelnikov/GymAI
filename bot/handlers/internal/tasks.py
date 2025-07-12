from datetime import datetime, timedelta

from aiohttp import web
from aiogram import Bot
from loguru import logger

from bot.keyboards import workout_survey_kb, program_view_kb
from bot.texts.text_manager import msg_text
from bot.utils.profiles import get_clients_to_survey
from config.env_settings import settings
from core.payment_processor import PaymentProcessor
from core.cache import Cache
from core.enums import CoachType
from bot.utils.chat import send_message
from aiogram.enums import ParseMode
from core.services import APIService
from core.ai_coach.base import BaseAICoach


async def internal_send_daily_survey(request: web.Request) -> web.Response:
    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        return web.json_response({"detail": "Forbidden"}, status=403)

    bot: Bot = request.app["bot"]
    try:
        clients = await get_clients_to_survey()
    except Exception as e:
        logger.error(f"Unexpected error in retrieving clients: {e}")
        return web.json_response({"detail": str(e)}, status=500)

    if not clients:
        logger.info("No clients to survey today")
        return web.json_response({"result": "no_clients"})

    yesterday = (datetime.now() - timedelta(days=1)).strftime("%A").lower()

    for client_profile in clients:
        try:
            await bot.send_message(
                chat_id=client_profile.tg_id,
                text=msg_text("have_you_trained", client_profile.language),
                reply_markup=workout_survey_kb(client_profile.language, yesterday),
                disable_notification=True,
            )
            logger.info(f"Survey sent to profile {client_profile.id}")
        except Exception as e:
            logger.error(f"Survey push failed for profile_id={client_profile.id}: {e}")

    return web.json_response({"result": "ok"})


async def internal_export_coach_payouts(request: web.Request) -> web.Response:
    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        return web.json_response({"detail": "Forbidden"}, status=403)

    try:
        await PaymentProcessor.export_coach_payouts()
        return web.json_response({"result": "ok"})
    except Exception as e:
        logger.exception(f"Failed to export coach payouts: {e}")
        return web.json_response({"detail": str(e)}, status=500)


async def internal_send_workout_result(request: web.Request, *, ai_coach: type[BaseAICoach]) -> web.Response:
    """Forward workout survey result to a coach or AI system."""

    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        return web.json_response({"detail": "Forbidden"}, status=403)

    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"detail": "Invalid JSON"}, status=400)

    coach_id = payload.get("coach_id")
    client_id = payload.get("client_id")
    text = payload.get("text")

    if not coach_id or not client_id or text is None:
        return web.json_response({"detail": "Missing parameters"}, status=400)

    bot: Bot = request.app["bot"]
    coach = await Cache.coach.get_coach(int(coach_id))
    if not coach:
        return web.json_response({"detail": "Coach not found"}, status=404)

    if coach.coach_type == CoachType.ai:
        await ai_coach.save_user_message(str(text), chat_id=int(client_id), client_id=int(client_id))
        client = await Cache.client.get_client(int(client_id))
        profile = await APIService.profile.get_profile(client.profile)
        lang = profile.language if profile else settings.DEFAULT_LANG
        program_text = await ai_coach.process_workout_result(int(client_id), str(text), lang)
        if profile is not None and program_text:
            await bot.send_message(
                chat_id=profile.tg_id,
                text=msg_text("new_program", profile.language),
                parse_mode=ParseMode.HTML,
            )
            await bot.send_message(
                chat_id=profile.tg_id,
                text=msg_text("program_page", profile.language).format(program=program_text, day=1),
                reply_markup=program_view_kb(profile.language),
                parse_mode=ParseMode.HTML,
            )
    else:
        await send_message(
            recipient=coach,
            text=str(text),
            bot=bot,
            state=None,
            include_incoming_message=False,
        )

    return web.json_response({"result": "ok"})
