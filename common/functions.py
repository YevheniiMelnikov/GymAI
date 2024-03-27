import os

from aiogram import Bot
from dotenv import load_dotenv

load_dotenv()
bot = Bot(os.environ.get("BOT_TOKEN"))


async def get_person_by_id(tg_user_id):
    pass
    # try:
    #     person = Person.objects.get(tg_user_id=tg_user_id)
    #     return person
    # except Person.DoesNotExist:
    #     return None


async def add_user_to_db(user_id: int, lang: str) -> None:
    pass


async def edit_person(user_id: int, data: dict[str, str]) -> None:
    pass
