from datetime import datetime, timedelta

from aiohttp import web
from aiogram import Bot
from loguru import logger

from bot.keyboards import workout_survey_kb
from bot.texts.text_manager import msg_text
from bot.utils.profiles import get_clients_to_survey
from config.env_settings import settings
from core.payment_processor import PaymentProcessor


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


async def internal_process_unclosed_payments(request: web.Request) -> web.Response:
    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        return web.json_response({"detail": "Forbidden"}, status=403)

    try:
        await PaymentProcessor.process_unclosed_payments()
        return web.json_response({"result": "ok"})
    except Exception as e:
        logger.exception(f"Failed to process unclosed payments: {e}")
        return web.json_response({"detail": str(e)}, status=500)
