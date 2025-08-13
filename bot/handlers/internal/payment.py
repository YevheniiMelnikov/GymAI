from aiohttp import web
from loguru import logger

from core.payment_processor import payment_processor
from core.cache import Cache
from aiogram import Bot
from bot.utils.chat import send_message, client_request
from config.app_settings import settings


async def internal_payment_handler(request: web.Request) -> web.Response:
    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        return web.json_response({"detail": "Forbidden"}, status=403)

    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"detail": "Invalid JSON"}, status=400)

    order_id = payload.get("order_id")
    status_ = payload.get("status")
    err_description = payload.get("err_description", "")

    if not order_id or not status_:
        return web.json_response({"detail": "Missing order_id or status"}, status=400)

    try:
        await payment_processor.handle_webhook_event(order_id, status_, err_description)
        return web.json_response({"result": "ok"})
    except Exception as e:
        logger.exception(f"Payment processing failed for {order_id}: {e}")
        return web.json_response({"detail": str(e)}, status=500)


async def internal_send_payment_message(request: web.Request) -> web.Response:
    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        return web.json_response({"detail": "Forbidden"}, status=403)

    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"detail": "Invalid JSON"}, status=400)

    client_profile_id = payload.get("client_id")
    text = payload.get("text")

    if not client_profile_id or not text:
        return web.json_response({"detail": "Missing client_id or text"}, status=400)

    bot: Bot = request.app["bot"]

    try:
        client = await Cache.client.get_client(int(client_profile_id))
        if not client:
            return web.json_response({"detail": "Client not found"}, status=404)
        await send_message(
            recipient=client,
            text=text,
            bot=bot,
            state=None,
            include_incoming_message=False,
        )
        return web.json_response({"result": "ok"})
    except Exception as e:
        logger.error(f"Failed to send payment message: {e}")
        return web.json_response({"detail": str(e)}, status=500)


async def internal_client_request(request: web.Request) -> web.Response:
    if request.headers.get("Authorization") != f"Api-Key {settings.API_KEY}":
        return web.json_response({"detail": "Forbidden"}, status=403)

    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"detail": "Invalid JSON"}, status=400)

    coach_profile_id = payload.get("coach_id")
    client_profile_id = payload.get("client_id")
    data = payload.get("data", {})

    if not coach_profile_id or not client_profile_id:
        return web.json_response({"detail": "Missing coach_id or client_id"}, status=400)

    bot: Bot = request.app["bot"]

    try:
        coach = await Cache.coach.get_coach(int(coach_profile_id))
        client = await Cache.client.get_client(int(client_profile_id))
        if not coach or not client:
            return web.json_response({"detail": "Coach or client not found"}, status=404)
        await client_request(coach=coach, client=client, data=data, bot=bot)
        return web.json_response({"result": "ok"})
    except Exception as e:
        logger.exception(f"Failed to process client request: {e}")
        return web.json_response({"detail": str(e)}, status=500)
