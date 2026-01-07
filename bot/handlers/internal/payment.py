import inspect

from aiohttp import web
from loguru import logger

from core.containers import get_container
from core.cache import Cache
from aiogram import Bot
from ...utils.bot import send_message
from .auth import require_internal_auth


@require_internal_auth
async def internal_payment_handler(request: web.Request) -> web.Response:
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
        processor = get_container().payment_processor()
        if inspect.isawaitable(processor):
            processor = await processor
        await processor.handle_webhook_event(order_id, status_, err_description)
        return web.json_response({"result": "ok"})
    except Exception as e:
        logger.exception(f"Payment processing failed for {order_id}: {e}")
        return web.json_response({"detail": str(e)}, status=500)


@require_internal_auth
async def internal_send_payment_message(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"detail": "Invalid JSON"}, status=400)

    profile_id = payload.get("profile_id")
    text = payload.get("text")

    if not profile_id or not text:
        return web.json_response({"detail": "Missing profile_id or text"}, status=400)

    bot: Bot = request.app["bot"]

    try:
        profile = await Cache.profile.get_record(int(profile_id))
        if not profile:
            return web.json_response({"detail": "Profile not found"}, status=404)
        await send_message(
            recipient=profile,
            text=text,
            bot=bot,
            state=None,
            include_incoming_message=False,
        )
        return web.json_response({"result": "ok"})
    except Exception as e:
        logger.error(f"Failed to send payment message: {e}")
        return web.json_response({"detail": str(e)}, status=500)
