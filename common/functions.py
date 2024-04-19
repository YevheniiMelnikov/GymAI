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
    # token = await user_service.get_token()
    if user := await user_service.current_user(token=None):  # TODO: PASS TOKEN
        if user.status == "client":
            await state.set_state(States.client_menu)
            await message.answer(
                text=translate(MessageText.welcome, lang=lang).format(name=user.username),
                reply_markup=client_menu_keyboard(lang),
            )
        elif user.status == "coach":
            await state.set_state(States.coach_menu)
            await message.answer(
                text=translate(MessageText.welcome, lang=lang).format(name=user.username),
                reply_markup=coach_menu_keyboard(lang),
            )


async def register_user(message: Message, state: FSMContext, data: dict) -> None:
    await state.update_data(email=message.text)
    if profile := await user_service.sign_up(
        username=data["username"],
        password=data["password"],
        email=message.text,
        status=data["account_type"],
        language=data["lang"],
    ):
        logger.info(f"User {message.from_user.id} registered")
        auth_token = await user_service.log_in(username=data["username"], password=data["password"])
        user_service.session.set_profile(profile, auth_token, message.from_user.id)
        await message.answer(text=translate(MessageText.registration_successful, lang=data["lang"]))
        await show_main_menu(message, state, data["lang"])
        await state.clear()
    else:
        await message.answer(text=translate(MessageText.unexpected_error, lang=data["lang"]))
        await state.clear()
        await state.set_state(States.username)
        await message.answer(text=translate(MessageText.username, lang=data["lang"]))


async def sign_in(message: Message, state: FSMContext, data: dict) -> None:
    if auth_token := await user_service.log_in(username=data["username"], password=message.text):
        if profile := await user_service.current_user(auth_token):
            user_service.session.set_profile(profile, auth_token, telegram_id=message.from_user.id)
            await message.answer(text=translate(MessageText.signed_in, lang=data["lang"]))
            await show_main_menu(message, state, data["lang"])
            await message.delete()
        else:
            await message.answer(text=translate(MessageText.unexpected_error, lang=data["lang"]))
            await state.set_state(States.username)
            await message.answer(text=translate(MessageText.username, lang=data["lang"]))
            await message.delete()
    else:
        await message.answer(text=translate(MessageText.invalid_credentials, lang=data["lang"]))
        await state.set_state(States.username)
        await message.answer(text=translate(MessageText.username, lang=data["lang"]))
        await message.delete()


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
