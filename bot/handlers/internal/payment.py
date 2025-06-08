from aiohttp import web
from loguru import logger

from core.payment_processor import PaymentProcessor
from config.env_settings import settings


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
        await PaymentProcessor.handle_webhook_event(order_id, status_, err_description)
        return web.json_response({"result": "ok"})
    except Exception as e:
        logger.exception(f"Payment processing failed for {order_id}: {e}")
        return web.json_response({"detail": str(e)}, status=500)
