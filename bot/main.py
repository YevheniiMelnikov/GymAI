import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage

from loguru import logger

from bot.utils.web import setup_app, start_web_app
from config.logger import configure_loguru
from core.utils.idempotency import close_redis as close_idempotency

from config.app_settings import settings
from bot.middlewares import ProfileMiddleware
from bot.handlers import configure_routers
from core.cache.base import BaseCacheManager
from bot.utils.bot import set_bot_commands, build_ping_url, check_webhook_alive
from core.containers import create_container, set_container, get_container
from core.services.internal import APIService


async def on_shutdown(bot: Bot) -> None:
    await bot.session.close()
    await close_idempotency()


async def main() -> None:
    configure_loguru()

    if not await BaseCacheManager.healthcheck():
        raise SystemExit("Redis is not responding to ping — exiting")

    container = create_container()
    set_container(container)
    APIService.configure(get_container)
    container.config.bot_token.from_value(settings.BOT_TOKEN)  # type: ignore[attr-defined]
    container.config.parse_mode.from_value("HTML")  # type: ignore[attr-defined]
    container.wire(modules=["bot.utils.other", "core.tasks"])
    init_result = container.init_resources()
    if init_result is not None:
        await init_result

    bot = container.bot()
    await bot.delete_webhook(drop_pending_updates=True)
    webhook_url = settings.WEBHOOK_URL
    if webhook_url is None:
        raise ValueError("WEBHOOK_URL must be set")
    await bot.set_webhook(url=webhook_url)
    await set_bot_commands(bot)

    dp = Dispatcher(storage=RedisStorage.from_url(settings.REDIS_URL))
    dp.message.middleware.register(ProfileMiddleware())
    dp.callback_query.middleware.register(ProfileMiddleware())
    dp.shutdown.register(on_shutdown)
    configure_routers(dp)

    app = web.Application()
    app["bot"] = bot
    await setup_app(app, bot, dp)
    runner = await start_web_app(app)

    # Webhook/HTTP server healthcheck
    ping_url = build_ping_url(webhook_url, settings.WEBHOOK_PATH)
    if not await check_webhook_alive(ping_url):
        logger.critical("Webhook did not respond — stopping")
        await runner.cleanup()
        dp.shutdown()
        shutdown_result = container.shutdown_resources()
        if shutdown_result is not None:
            await shutdown_result
        raise SystemExit("Webhook healthcheck failed — exiting")

    logger.success("Bot started")
    stop_event = asyncio.Event()

    try:
        await stop_event.wait()
    except Exception as e:
        logger.critical(f"Bot encountered an error: {e}")
    finally:
        await runner.cleanup()
        dp.shutdown()
        shutdown_result = container.shutdown_resources()
        if shutdown_result is not None:
            await shutdown_result


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Bot stopped")
