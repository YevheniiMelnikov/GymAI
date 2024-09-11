import asyncio
import os

import loguru
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage
from dotenv import load_dotenv

from backup.backup_manager import backup_scheduler
from bot.handlers.chat_handler import chat_router
from bot.handlers.command_handler import cmd_router
from bot.handlers.invalid_content_handler import invalid_content_router
from bot.handlers.main_handler import main_router
from bot.handlers.payment_handler import payment_router
from bot.handlers.questionnaire_handler import questionnaire_router
from bot.handlers.registration_handler import register_router
from bot.handlers.workouts_handler import program_router
from common.functions.chat import sub_router
from common.functions.utils import set_bot_commands
from common.payment_manager import payment_handler
from common.subscription_manager import subscription_manager
from common.workout_scheduler import survey_router, workout_scheduler

load_dotenv()
logger = loguru.logger


async def main() -> None:
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        logger.error("BOT_TOKEN environment variable not found.")
        return

    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    redis_url = os.getenv("REDIS_URL")
    dp = Dispatcher(storage=RedisStorage.from_url(f"{redis_url}/0"))
    dp.include_routers(
        cmd_router,
        sub_router,
        survey_router,
        main_router,
        chat_router,
        register_router,
        questionnaire_router,
        invalid_content_router,
        program_router,
        payment_router,
    )

    logger.info("Starting bot ...")
    await workout_scheduler()
    await backup_scheduler()
    await subscription_manager()
    payment_handler.start_payment_checker()
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await set_bot_commands()
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Failed to start the bot due to an exception: {e}")


if __name__ == "__main__":
    asyncio.run(main())
