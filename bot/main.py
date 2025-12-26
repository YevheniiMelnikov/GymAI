import asyncio
import signal
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from loguru import logger

from bot.utils.web import setup_app, start_web_app, build_ping_url
from config.logger import configure_loguru
from core.utils.idempotency import close_redis as close_idempotency
from config.app_settings import settings
from bot.middlewares import ProfileMiddleware
from bot.handlers import configure_routers
from core.cache.base import BaseCacheManager
from bot.utils.bot import set_bot_commands, check_webhook_alive
from dependency_injector import providers

from core.containers import create_container, set_container, get_container
from core.infra.payment import TaskPaymentNotifier
from core.services.internal import APIService


async def on_shutdown(bot: Bot) -> None:
    await bot.session.close()
    await close_idempotency()


async def main() -> None:
    configure_loguru()

    if not await BaseCacheManager.healthcheck():
        raise SystemExit("Redis is not responding to ping — exiting")

    container = create_container()
    container.notifier.override(providers.Factory(TaskPaymentNotifier))
    set_container(container)
    APIService.configure(get_container)
    container.config.bot_token.from_value(settings.BOT_TOKEN)  # type: ignore[attr-defined]
    container.config.parse_mode.from_value("HTML")  # type: ignore[attr-defined]
    container.wire(
        modules=[
            "bot.utils.other",
        ]
    )
    init_result = container.init_resources()
    if init_result is not None:
        await init_result

    bot = container.bot()
    await bot.delete_webhook(drop_pending_updates=True)
    webhook_url = settings.WEBHOOK_URL
    if webhook_url is None:
        raise ValueError("WEBHOOK_URL must be set")
    await bot.set_webhook(
        url=webhook_url,
        secret_token=settings.SECRET_KEY,
        allowed_updates=["message", "callback_query"],
    )
    await set_bot_commands(bot)

    dp = Dispatcher(storage=RedisStorage.from_url(settings.REDIS_URL))
    dp.message.middleware.register(ProfileMiddleware())
    dp.callback_query.middleware.register(ProfileMiddleware())
    dp.shutdown.register(on_shutdown)
    configure_routers(dp)

    app = web.Application()
    app["bot"] = bot

    async def health_ask_ai(request: web.Request) -> web.Response:
        notifier = get_container().notifier()
        stats = notifier.get_stats()  # pyrefly: ignore[missing-attribute]
        return web.json_response(stats)

    app.router.add_get("/health/ask_ai", health_ask_ai)

    await setup_app(app, bot, dp)

    runner = None
    cleaned = False
    try:
        runner = await start_web_app(app)

        ping_url = build_ping_url(settings.WEBHOOK_URL)
        if not await check_webhook_alive(ping_url):
            if runner is not None:
                await runner.cleanup()
            await dp.emit_shutdown(bot=bot)
            await dp.storage.close()
            shutdown_result = container.shutdown_resources()
            if shutdown_result is not None:
                await shutdown_result
            cleaned = True
            raise SystemExit("Webhook healthcheck failed — exiting")

        logger.success("Bot started")
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for s in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(s, lambda *_: stop_event.set())
        await stop_event.wait()
    finally:
        if not cleaned:
            if runner is not None:
                await runner.cleanup()
            await dp.emit_shutdown(bot=bot)
            await dp.storage.close()
            shutdown_result = container.shutdown_resources()
            if shutdown_result is not None:
                await shutdown_result


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Bot stopped")
