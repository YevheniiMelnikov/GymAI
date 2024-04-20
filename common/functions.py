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


async def show_main_menu(message: Message, state: FSMContext, lang: str):
    profile = user_service.session.get_current_profile_by_tg_id(message.from_user.id)
    menu = client_menu_keyboard if profile.status == "client" else coach_menu_keyboard
    await state.set_state(States.client_menu if profile.status == "client" else States.coach_menu)
    await message.answer(text=translate(MessageText.main_menu, lang=lang), reply_markup=menu(lang))


async def register_user(message: Message, state: FSMContext, data: dict) -> None:
    await state.update_data(email=message.text)
    profile = await user_service.sign_up(
        username=data["username"],
        password=data["password"],
        email=message.text,
        status=data["account_type"],
        language=data["lang"],
    )

    if not profile:
        logger.error(f"Registration failed for user {message.from_user.id}")
        await handle_registration_failure(message, state, data["lang"])
        return

    logger.info(f"User {message.from_user.id} registered")
    auth_token = await user_service.log_in(username=data["username"], password=data["password"])

    if not auth_token:
        logger.error(f"Login failed for user {message.from_user.id} after registration")
        await handle_registration_failure(message, state, data["lang"])
        return

    logger.info(f"User {message.from_user.id} logged in")
    user_service.session.set_profile(profile, auth_token, message.from_user.id)
    await message.answer(text=translate(MessageText.registration_successful, lang=data["lang"]))
    await show_main_menu(message, state, data["lang"])


async def sign_in(message: Message, state: FSMContext, data: dict) -> None:
    auth_token = await user_service.log_in(username=data["username"], password=message.text)
    if not auth_token:
        attempts = data.get("login_attempts", 0) + 1
        await state.update_data(login_attempts=attempts)
        if attempts >= 3:
            await message.answer(text=translate(MessageText.reset_password_offer, lang=data["lang"]))
        else:
            await message.answer(text=translate(MessageText.invalid_credentials, lang=data["lang"]))
            await state.set_state(States.username)
            await message.answer(text=translate(MessageText.username, lang=data["lang"]))
        await message.delete()
        return

    logger.info(f"User {message.from_user.id} logged in")
    profile = await user_service.get_profile_by_username(data["username"], auth_token)
    if not profile:
        await message.answer(text=translate(MessageText.unexpected_error, lang=data["lang"]))
        await state.set_state(States.username)
        await message.answer(text=translate(MessageText.username, lang=data["lang"]))
        await message.delete()
        return

    await state.update_data(login_attempts=0)
    user_service.session.set_profile(profile, auth_token, telegram_id=message.from_user.id)
    logger.info(f"Profile {profile.id} set for user {message.from_user.id}")
    await message.answer(text=translate(MessageText.signed_in, lang=data["lang"]))
    await show_main_menu(message, state, data["lang"])
    await message.delete()


async def handle_registration_failure(message: Message, state: FSMContext, lang: str) -> None:
    await message.answer(text=translate(MessageText.unexpected_error, lang=lang))
    await state.clear()
    await state.set_state(States.username)
    await message.answer(text=translate(MessageText.username, lang=lang))


def validate_birth_date(date_str: str) -> bool:
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    if not pattern.match(date_str):
        return False

    year, month, day = map(int, date_str.split("-"))
    if not (1900 <= year <= 2100 and 1 <= month <= 12):
        return False

    if (month in [4, 6, 9, 11] and day > 30) or (
        month == 2 and day > (29 if (year % 4 == 0 and year % 100 != 0) or year % 400 == 0 else 28)
    ):
        return False

    return 1 <= day <= 31


def validate_email(email: str) -> bool:
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,4}$"
    return bool(re.match(pattern, email))
