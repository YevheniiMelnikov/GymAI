import os
import re

import loguru
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from dotenv import load_dotenv

from bot.keyboards import client_menu_keyboard, coach_menu_keyboard
from bot.states import States
from common.user_service import user_service
from texts.text_manager import MessageText, translate

logger = loguru.logger
load_dotenv()
bot = Bot(os.environ.get("BOT_TOKEN"))
BACKEND_URL = os.environ.get("BACKEND_URL")


async def show_main_menu(message: Message, state: FSMContext, lang: str) -> None:
    if person := await user_service.current_person():
        if person.status == "client":
            await state.set_state(States.client_menu)
            await message.answer(
                text=translate(MessageText.welcome, lang=lang).format(name=person.username),
                reply_markup=client_menu_keyboard(lang),
            )
        elif person.status == "coach":
            await state.set_state(States.coach_menu)
            await message.answer(
                text=translate(MessageText.welcome, lang=lang).format(name=person.username),
                reply_markup=coach_menu_keyboard(lang),
            )


def validate_birth_date(date_str: str) -> bool:
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    if not pattern.match(date_str):
        return False

    year, month, day = map(int, date_str.split("-"))
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


def validate_email(email):
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,4}$"
    return bool(re.match(pattern, email))
