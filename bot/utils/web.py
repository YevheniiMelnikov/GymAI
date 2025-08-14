from urllib.parse import urlsplit, urlunsplit

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

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


async def ping_handler(_: web.Request) -> web.Response:
    return web.json_response({"ok": True})


def build_ping_url(webhook_url: str, webhook_path: str) -> str:
    s = urlsplit(webhook_url)
    path = webhook_path.rstrip("/") + "/__ping"
    return urlunsplit((s.scheme, s.netloc, path, "", ""))


async def setup_app(app: web.Application, bot: Bot, dp: Dispatcher) -> None:
    path = settings.WEBHOOK_PATH.rstrip("/")
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=path)
    app.router.add_get(f"/__ping/", ping_handler)
    app.router.add_post("/internal/payments/process/", internal_payment_handler)
    app.router.add_post("/internal/payments/send_message/", internal_send_payment_message)
    app.router.add_post("/internal/payments/client_request/", internal_client_request)
    app.router.add_post("/internal/tasks/send_daily_survey/", internal_send_daily_survey)
    app.router.add_post("/internal/tasks/send_workout_result/", internal_send_workout_result)
    app.router.add_post("/internal/tasks/export_coach_payouts/", internal_export_coach_payouts)
    app.router.add_post("/internal/tasks/prune_cognee/", internal_prune_cognee)
    setup_application(app, dp, bot=bot)


async def start_web_app(app: web.Application) -> web.AppRunner:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=settings.WEB_SERVER_HOST, port=settings.WEBHOOK_PORT)
    await site.start()
    return runner
