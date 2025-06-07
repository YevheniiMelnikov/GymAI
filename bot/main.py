import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from loguru import logger

from bot.handlers.internal.payment import internal_payment_handler
from config.env_settings import Settings
from bot.middlewares import ProfileMiddleware
from bot.handlers import configure_routers
from core.cache.base import BaseCacheManager
from bot.utils.other import set_bot_commands
from core.containers import App


async def on_shutdown(bot: Bot) -> None:
    await bot.session.close()


async def start_web_app(app: web.Application) -> web.AppRunner:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=Settings.WEB_SERVER_HOST, port=Settings.WEBHOOK_PORT)
    await site.start()
    return runner


async def main() -> None:
    if not await BaseCacheManager.healthcheck():
        raise SystemExit("Redis is not responding to ping — exiting")

    container = App()
    container.config.bot_token.from_value(Settings.BOT_TOKEN)  # type: ignore[attr-defined]
    container.config.parse_mode.from_value("HTML")  # type: ignore[attr-defined]
    container.wire(modules=["bot.handlers", "bot.utils"])
    bot = container.bot()
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(url=Settings.WEBHOOK_URL)
    await set_bot_commands(bot)

    dp = Dispatcher(storage=RedisStorage.from_url(Settings.REDIS_URL))
    dp.message.middleware.register(ProfileMiddleware())
    dp.shutdown.register(on_shutdown)
    configure_routers(dp)

    app = web.Application()
    app["bot"] = bot
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=Settings.WEBHOOK_PATH)
    app.router.add_post("/internal/payment/process/", internal_payment_handler)
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
