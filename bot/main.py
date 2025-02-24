import asyncio
import loguru
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from bot.middlewares import ProfileMiddleware
from common.settings import settings
from schedulers import backup_scheduler, subscription_scheduler, workout_scheduler
from core import payment_processor
from bot.handlers.routers_configurator import configure_routers
from functions.utils import set_bot_commands

logger = loguru.logger


async def on_startup() -> None:
    await set_bot_commands()
    await workout_scheduler.run()
    await backup_scheduler.run()
    await subscription_scheduler.run()
    await payment_processor.run()


async def on_shutdown(bot: Bot) -> None:
    await bot.session.close()
    await backup_scheduler.shutdown()
    await subscription_scheduler.shutdown()


async def start_web_app(app: web.Application) -> web.AppRunner:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=settings.WEB_SERVER_HOST, port=settings.WEBHOOK_PORT)
    await site.start()
    return runner


async def shutdown_web_app(runner: web.AppRunner):
    await runner.cleanup()


async def main() -> None:
    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=RedisStorage.from_url(settings.REDIS_URL))
    dp.message.middleware.register(ProfileMiddleware())
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    configure_routers(dp)

    await bot.set_webhook(url=settings.WEBHOOK_URL)
    app = web.Application()
    app["bot"] = bot

    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=settings.WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    runner = await start_web_app(app)
    logger.info("Bot started")
    stop_event = asyncio.Event()

    try:
        await stop_event.wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down bot...")
    finally:
        await shutdown_web_app(runner)
        dp.shutdown()
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")
