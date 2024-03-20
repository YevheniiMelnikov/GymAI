import asyncio
import os

from aiogram import Bot, Dispatcher
from dotenv import load_dotenv

from bot.handlers import main_menu
from common.logger import logger


async def main() -> None:
    load_dotenv()
    bot = Bot(token=os.getenv("BOT_TOKEN"))  # type: ignore[arg-type]
    dp = Dispatcher()
    dp.include_router(main_menu.start_router)
    logger.info("Starting bot ...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
