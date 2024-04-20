import asyncio
import os

import loguru
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from dotenv import load_dotenv

from bot.commands import bot_commands
from bot.handlers.command_handler import cmd_router
from bot.handlers.invalid_content_handler import invalid_content_router
from bot.handlers.main_handler import main_router
from bot.handlers.registration_handler import register_router

load_dotenv()
logger = loguru.logger


async def main() -> None:
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        logger.error("BOT_TOKEN environment variable not found.")
        return

    bot = Bot(token=bot_token, parse_mode="HTML")
    redis_url = os.getenv("REDIS_URL")
    dp = Dispatcher(storage=RedisStorage.from_url(f"{redis_url}/0"))
    dp.include_routers(cmd_router, main_router, register_router, invalid_content_router)

    logger.info("Starting bot ...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_my_commands(bot_commands.get("ua", []))
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Failed to start the bot due to an exception: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
