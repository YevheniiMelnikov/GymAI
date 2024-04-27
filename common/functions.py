import os
from contextlib import suppress

import loguru
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, Message
from dotenv import load_dotenv

from bot.keyboards import client_menu_keyboard, coach_menu_keyboard
from bot.states import States
from common.user_service import user_service
from texts.text_manager import MessageText, resource_manager, translate

logger = loguru.logger
load_dotenv()
bot = Bot(os.environ.get("BOT_TOKEN"))
BACKEND_URL = os.environ.get("BACKEND_URL")


async def show_main_menu(message: Message, state: FSMContext, lang: str, tg_id: int | None = None) -> None:
    profile = user_service.storage.get_current_profile_by_tg_id(tg_id or message.from_user.id)
    menu = client_menu_keyboard if profile.status == "client" else coach_menu_keyboard
    await state.clear()
    await state.set_state(States.main_menu)
    await state.update_data(id=tg_id or message.from_user.id)
    await message.answer(text=translate(MessageText.main_menu, lang=lang), reply_markup=menu(lang))
    with suppress(TelegramBadRequest):
        await message.delete()


async def register_user(message: Message, state: FSMContext, data: dict) -> None:
    await state.update_data(email=message.text)
    if not await user_service.sign_up(
        username=data["username"],
        password=data["password"],
        email=message.text,
        status=data["account_type"],
        language=data["lang"],
    ):
        logger.error(f"Registration failed for user {message.from_user.id}")
        await handle_registration_failure(message, state, data["lang"])
        return

    logger.info(f"User {message.from_user.id} registered")
    token = await user_service.log_in(username=data["username"], password=data["password"])

    if not token:
        logger.error(f"Login failed for user {message.from_user.id} after registration")
        await handle_registration_failure(message, state, data["lang"])
        return

    logger.info(f"User {message.from_user.id} logged in")
    profile_data = await user_service.get_profile_by_username(data["username"], token)
    user_service.storage.set_profile(
        profile=profile_data,
        username=data["username"],
        auth_token=token,
        telegram_id=message.from_user.id,
        email=message.text,
    )
    await message.answer(text=translate(MessageText.registration_successful, lang=data["lang"]))
    await show_main_menu(message, state, data["lang"])


async def sign_in(message: Message, state: FSMContext, data: dict) -> None:
    token = await user_service.log_in(username=data["username"], password=message.text)
    if not token:
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
    profile = await user_service.get_profile_by_username(data["username"], token)
    if not profile:
        await message.answer(text=translate(MessageText.unexpected_error, lang=data["lang"]))
        await state.set_state(States.username)
        await message.answer(text=translate(MessageText.username, lang=data["lang"]))
        await message.delete()
        return

    await state.update_data(login_attempts=0)
    user_service.storage.set_profile(
        profile=profile, username=data["username"], auth_token=token, telegram_id=message.from_user.id
    )
    logger.info(f"profile_id {profile.id} set for user {message.from_user.id}")
    await message.answer(text=translate(MessageText.signed_in, lang=data["lang"]))
    await show_main_menu(message, state, data["lang"])
    await message.delete()


async def handle_registration_failure(message: Message, state: FSMContext, lang: str) -> None:
    await message.answer(text=translate(MessageText.unexpected_error, lang=lang))
    await state.clear()
    await state.set_state(States.username)
    await message.answer(text=translate(MessageText.username, lang=lang))


async def set_bot_commands(lang: str = "ua") -> None:
    command_texts = resource_manager.commands
    commands = [BotCommand(command=cmd, description=desc[lang]) for cmd, desc in command_texts.items()]
    await bot.set_my_commands(commands)
