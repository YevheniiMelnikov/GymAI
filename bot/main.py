import asyncio

import loguru
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage
from dotenv import load_dotenv

from core.settings import settings
from schedulers.backup_scheduler import run_backup_scheduler
from bot.handlers.routers_configurator import configure_routers
from functions.utils import set_bot_commands
from schedulers.payment_scheduler import payment_processor
from schedulers.subscription_scheduler import run_subscription_scheduler
from schedulers.workout_scheduler import run_workout_scheduler

load_dotenv()
logger = loguru.logger


async def main() -> None:
    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=RedisStorage.from_url(f"{settings.REDIS_URL}"))
    configure_routers(dp)

    await run_workout_scheduler()
    await run_backup_scheduler()
    await run_subscription_scheduler()
    payment_processor.run_payment_checker()

    logger.info("Starting bot ...")
    await bot.delete_webhook(drop_pending_updates=True)
    await set_bot_commands()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
