from urllib.parse import urlparse

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from loguru import logger

from bot.handlers.internal import (
    internal_payment_handler,
    internal_send_payment_message,
    internal_client_request,
    internal_send_daily_survey,
    internal_send_workout_result,
    internal_export_coach_payouts,
    internal_prune_cognee,
)
from config.app_settings import settings


async def setup_app(app: web.Application, bot: Bot, dp: Dispatcher) -> None:
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=settings.WEBHOOK_PATH)
    app.router.add_post("/internal/payments/process/", internal_payment_handler)
    app.router.add_post("/internal/payments/send_message/", internal_send_payment_message)
    app.router.add_post("/internal/payments/client_request/", internal_client_request)
    app.router.add_post("/internal/tasks/send_daily_survey/", internal_send_daily_survey)
    app.router.add_post(
        "/internal/tasks/send_workout_result/",
        internal_send_workout_result,
    )
    app.router.add_post(
        "/internal/tasks/export_coach_payouts/",
        internal_export_coach_payouts,
    )
    app.router.add_post(
        "/internal/tasks/prune_cognee/",
        internal_prune_cognee,
    )
    setup_application(app, dp, bot=bot)


async def start_web_app(app: web.Application) -> web.AppRunner:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=settings.WEB_SERVER_HOST, port=settings.WEBHOOK_PORT)
    await site.start()
    return runner


def get_webapp_url(page_type: str) -> str | None:
    source = settings.WEBAPP_PUBLIC_URL
    if not source:
        logger.error("WEBAPP_PUBLIC_URL is not configured; webapp button hidden")
        return None
    parsed = urlparse(source)
    host = parsed.netloc or parsed.path.split("/")[0]
    base = f"{parsed.scheme or 'https'}://{host}"
    return f"{base}/webapp/?type={page_type}"
