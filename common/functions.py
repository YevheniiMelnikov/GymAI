import os
from typing import Type

from aiogram import Bot
from dotenv import load_dotenv

# from backend.accounts.models import Person
from common.storage import Storage

load_dotenv()
storage = Storage()
bot = Bot(os.environ.get("BOT_TOKEN"))


async def get_person_by_id(user_id: int):
    return await storage.get_person_by_id(user_id)


async def add_user_to_db(user_id: int, lang: str) -> None:
    await storage.add_person()


async def edit_person(user_id: int, data: dict[str, str]) -> None:
    await storage.edit_person(user_id, data)
