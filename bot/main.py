import asyncio

import loguru
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage

from bot.middlewares import ProfileMiddleware
from common.settings import settings
from schedulers import backup_scheduler, subscription_scheduler, workout_scheduler
from core import payment_processor
from bot.handlers.routers_configurator import configure_routers
from functions.utils import set_bot_commands

logger = loguru.logger


async def main() -> None:
    try:
        bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
        dp = Dispatcher(storage=RedisStorage.from_url(f"{settings.REDIS_URL}"))
        dp.message.middleware.register(ProfileMiddleware())
        configure_routers(dp)

        await workout_scheduler.run()
        await backup_scheduler.run()
        await subscription_scheduler.run()
        await payment_processor.run()

        logger.info("Starting bot ...")
        await bot.delete_webhook(drop_pending_updates=True)
        await set_bot_commands()
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"Error while starting bot: {e}")


if __name__ == "__main__":
    asyncio.run(main())
