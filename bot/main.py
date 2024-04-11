import asyncio
import os

import loguru
from aiogram import Bot, Dispatcher
from dotenv import load_dotenv

from bot.commands import bot_commands
from bot.handlers.command_handler import cmd_router
from bot.handlers.main_handler import main_router
from bot.handlers.registration_handler import register_router

logger = loguru.logger


async def main() -> None:
    load_dotenv()
    bot = Bot(token=os.getenv("BOT_TOKEN"), parse_mode="HTML")
    dp = Dispatcher()
    dp.include_router(register_router)
    dp.include_router(cmd_router)
    dp.include_router(main_router)
    logger.info("Starting bot ...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_my_commands(bot_commands["ua"])
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(e)


if __name__ == "__main__":
    asyncio.run(main())
