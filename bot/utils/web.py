from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit



from config.app_settings import settings

if TYPE_CHECKING:
    from aiohttp import web
    from aiogram import Bot, Dispatcher
else:  # pragma: no cover - runtime imports
    Bot = Dispatcher = Any


async def ping_handler(_: "web.Request") -> "web.Response":
    from aiohttp import web

    return web.json_response({"ok": True})


def build_ping_url(webhook_url: str | None) -> str:
    if webhook_url is None:
        raise ValueError("webhook_url must be set")
    s = urlsplit(webhook_url)
    path = settings.WEBHOOK_PATH.rstrip("/") + "/__ping"
    return urlunsplit((s.scheme, s.netloc, path, "", ""))


async def setup_app(app: "web.Application", bot: "Bot", dp: "Dispatcher") -> None:
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
    from bot.handlers.internal import (
        internal_payment_handler,
        internal_send_payment_message,
        internal_client_request,
        internal_send_daily_survey,
        internal_send_workout_result,
        internal_export_coach_payouts,
        internal_prune_cognee,
    )

    path = settings.WEBHOOK_PATH.rstrip("/")
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=path)
    app.router.add_get(f"{path}/__ping", ping_handler)
    app.router.add_post("/internal/payments/process/", internal_payment_handler)
    app.router.add_post("/internal/payments/send_message/", internal_send_payment_message)
    app.router.add_post("/internal/payments/client_request/", internal_client_request)
    app.router.add_post("/internal/tasks/send_daily_survey/", internal_send_daily_survey)
    app.router.add_post("/internal/tasks/send_workout_result/", internal_send_workout_result)
    app.router.add_post("/internal/tasks/export_coach_payouts/", internal_export_coach_payouts)
    app.router.add_post("/internal/tasks/prune_cognee/", internal_prune_cognee)
    setup_application(app, dp, bot=bot)


async def start_web_app(app: "web.Application") -> "web.AppRunner":
    from aiohttp import web

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(
        runner=runner,
        host=settings.WEB_SERVER_HOST,
        port=settings.BOT_PORT,
    )
    await site.start()
    return runner
