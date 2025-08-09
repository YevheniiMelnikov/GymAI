import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from loguru import logger
from config.logger import configure_loguru
from core.utils.idempotency import close_redis as close_idempotency

from bot.handlers.internal import (
    internal_payment_handler,
    internal_send_payment_message,
    internal_client_request,
    internal_export_coach_payouts,
    internal_send_daily_survey,
    internal_send_workout_result,
    internal_prune_cognee,
)
from config.app_settings import settings
from bot.middlewares import ProfileMiddleware
from bot.handlers import configure_routers
from core.cache.base import BaseCacheManager
from bot.utils.other import set_bot_commands
from core.containers import App


configure_loguru()


async def on_shutdown(bot: Bot) -> None:
    await bot.session.close()
    await close_idempotency()


async def start_web_app(app: web.Application) -> web.AppRunner:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=settings.WEB_SERVER_HOST, port=settings.WEBHOOK_PORT)
    await site.start()
    return runner


async def main() -> None:
    if not await BaseCacheManager.healthcheck():
        raise SystemExit("Redis is not responding to ping — exiting")

    container = App()
    container.config.bot_token.from_value(settings.BOT_TOKEN)  # type: ignore[attr-defined]
    container.config.parse_mode.from_value("HTML")  # type: ignore[attr-defined]
    container.wire(modules=["bot.utils.other", "core.tasks"])

    bot = container.bot()
    await bot.delete_webhook(drop_pending_updates=True)

    if settings.WEBHOOK_URL is None:
        raise ValueError("WEBHOOK_URL is not set in environment variables")

    await bot.set_webhook(url=settings.WEBHOOK_URL)
    await set_bot_commands(bot)

    dp = Dispatcher(storage=RedisStorage.from_url(settings.REDIS_URL))
    dp.message.middleware.register(ProfileMiddleware())
    dp.callback_query.middleware.register(ProfileMiddleware())
    dp.shutdown.register(on_shutdown)
    configure_routers(dp)

    app = web.Application()
    app["bot"] = bot

    if settings.WEBHOOK_PATH is None:
        raise ValueError("WEBHOOK_PATH is not set in environment variables")
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
    runner = await start_web_app(app)
    logger.success("Bot started")
    stop_event = asyncio.Event()

    try:
        await stop_event.wait()
    except Exception as e:
        logger.critical(f"Bot encountered an error: {e}")
    finally:
        await runner.cleanup()
        dp.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Bot stopped")
