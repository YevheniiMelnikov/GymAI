from __future__ import annotations

from typing import TYPE_CHECKING, Any

from config.app_settings import settings

if TYPE_CHECKING:
    from aiohttp import web
    from aiogram import Bot, Dispatcher
else:
    Bot = Dispatcher = Any


async def ping_handler(_: "web.Request") -> "web.Response":
    from aiohttp import web

    return web.json_response({"ok": True})


async def setup_app(app: "web.Application", bot: "Bot", dp: "Dispatcher") -> None:
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
    from bot.handlers.internal import (
        internal_payment_handler,
        internal_send_payment_message,
        internal_send_weekly_survey,
        internal_send_subscription_renewal,
        internal_ai_coach_plan_ready,
        internal_ai_answer_ready,
        internal_ai_diet_ready,
        internal_webapp_workout_action,
        internal_webapp_weekly_survey_submitted,
        internal_webapp_profile_balance,
        internal_webapp_profile_deleted,
    )

    path = settings.WEBHOOK_PATH.rstrip("/")
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=path)
    app["dp"] = dp
    app.router.add_get(f"{path}/__ping", ping_handler)
    app.router.add_post("/internal/payments/process/", internal_payment_handler)
    app.router.add_post("/internal/payments/send_message/", internal_send_payment_message)
    app.router.add_post("/internal/tasks/send_weekly_survey/", internal_send_weekly_survey)
    app.router.add_post("/internal/tasks/send_subscription_renewal/", internal_send_subscription_renewal)
    app.router.add_post("/internal/tasks/ai_plan_ready/", internal_ai_coach_plan_ready)
    app.router.add_post("/internal/tasks/ai_answer_ready/", internal_ai_answer_ready)
    app.router.add_post("/internal/tasks/ai_diet_ready/", internal_ai_diet_ready)
    app.router.add_post("/internal/webapp/workouts/action/", internal_webapp_workout_action)
    app.router.add_post(
        "/internal/webapp/weekly-survey/submitted/",
        internal_webapp_weekly_survey_submitted,
    )
    app.router.add_post("/internal/webapp/profile/balance/", internal_webapp_profile_balance)
    app.router.add_post("/internal/webapp/profile/deleted/", internal_webapp_profile_deleted)
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
