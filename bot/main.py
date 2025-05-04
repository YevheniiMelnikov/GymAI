import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from loguru import logger
from config.env_settings import Settings
from bot.middlewares import ProfileMiddleware
from bot.handlers.routers_configurator import configure_routers
from functions.utils import set_bot_commands
from core.payment_processor import PaymentProcessor
from core import workout_scheduler


async def on_startup() -> None:
    await set_bot_commands()
    await workout_scheduler.run()
    PaymentProcessor.run()


async def on_shutdown(bot: Bot) -> None:
    await bot.session.close()


async def start_web_app(app: web.Application) -> web.AppRunner:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=Settings.WEB_SERVER_HOST, port=Settings.WEBHOOK_PORT)
    await site.start()
    return runner


async def main() -> None:
    bot = Bot(token=Settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(url=Settings.WEBHOOK_URL)

    dp = Dispatcher(storage=RedisStorage.from_url(Settings.REDIS_URL))
    dp.message.middleware.register(ProfileMiddleware())
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    configure_routers(dp)

    app = web.Application()
    app["bot"] = bot
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=Settings.WEBHOOK_PATH)
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
