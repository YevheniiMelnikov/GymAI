import os
import re

import httpx
import loguru
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from dotenv import load_dotenv

from bot.keyboards import client_menu_keyboard, coach_menu_keyboard
from bot.states import States
from common.models import Person
from texts.text_manager import MessageText, translate

logger = loguru.logger
load_dotenv()
bot = Bot(os.environ.get("BOT_TOKEN"))
BACKEND_URL = os.environ.get("BACKEND_URL")


async def api_request(method: str, url: str, data: dict = None) -> tuple:
    logger.info(f"METHOD: {method.upper()} URL: {url} data: {data}")
    try:
        async with httpx.AsyncClient() as client:
            if method == "get":
                response = await client.get(url)
            elif method == "post":
                response = await client.post(url, data=data)
            elif method == "put":
                response = await client.put(url, data=data)
            elif method == "delete":
                response = await client.delete(url)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            return response.status_code, response.json()

    except Exception as e:
        logger.error(e)
        return None, None


async def create_person(data: dict) -> bool:
    url = f"{BACKEND_URL}/persons/"
    status_code, _ = await api_request("post", url, data)
    return status_code == 201 if status_code else False


async def get_person(tg_user_id: int) -> Person | None:
    url = f"{BACKEND_URL}/persons/{tg_user_id}/"
    status_code, user_data = await api_request("get", url)
    if user_data and "tg_user_id" in user_data:
        return Person.from_dict(user_data)
    else:
        return None


async def edit_person(tg_user_id: int, data: dict) -> bool:
    url = f"{BACKEND_URL}/person/{tg_user_id}/"
    status_code, _ = await api_request("put", url, data)
    return status_code == 200 if status_code else False


async def delete_person(tg_user_id: int) -> bool:
    url = f"{BACKEND_URL}/persons/{tg_user_id}/"
    status_code, _ = await api_request("delete", url)
    return status_code == 404 if status_code else False


async def set_data_and_next_state(
    message: Message, state: FSMContext, next_state: str, data: dict[str, str] | None = None
) -> None:
    await state.update_data(data)
    await state.set_state(next_state)
    await message.delete()


async def show_main_menu(message: Message, state: FSMContext, lang: str) -> None:
    person = await get_person(message.from_user.id)
    if person.status == "client":
        await state.set_state(States.client_menu)
        await message.answer(
            text=translate(MessageText.welcome, lang=lang).format(name=person.short_name),
            reply_markup=client_menu_keyboard(lang),
        )
    elif person.status == "coach":
        await state.set_state(States.coach_menu)
        await message.answer(
            text=translate(MessageText.welcome, lang=lang).format(name=person.short_name),
            reply_markup=coach_menu_keyboard(lang),
        )


async def validate_birth_date(date_str: str) -> bool:
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    if not pattern.match(date_str):
        return False

    year, month, day = map(int, date_str.split('-'))
    if year < 1900 or year > 2100:
        return False

    if month < 1 or month > 12:
        return False

    if day < 1 or day > 31:
        return False

    if month in [4, 6, 9, 11] and day > 30:
        return False

    if month == 2:
        if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0):
            if day > 29:
                return False
        elif day > 28:
            return False

    return True
