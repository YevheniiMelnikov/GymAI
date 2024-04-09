import os

import httpx
import loguru
from aiogram import Bot
from dotenv import load_dotenv

from bot.models import Person

logger = loguru.logger
load_dotenv()
bot = Bot(os.environ.get("BOT_TOKEN"))


async def get_person_by_id(tg_user_id: int) -> Person | None:
    try:
        async with httpx.AsyncClient() as client:
            request_url = "http://backend:8000/api/v1/persons_list/"
            result = await client.get(request_url)
            users_response = result.json()

            if "persons" in users_response:
                users_list = users_response["persons"]
                for user_data in users_list:
                    if user_data.get("tg_user_id") == tg_user_id:  # TODO: FIND BETTER SOLUTION
                        return Person.from_dict(user_data)

            return None

    except Exception as e:
        logger.error(e)
        return None


async def add_user_to_db(user_id: int, lang: str) -> None:
    pass


async def edit_person(user_id: int, data: dict[str, str]) -> None:
    pass
