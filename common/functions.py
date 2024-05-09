import os
from contextlib import suppress
from typing import Any

import loguru
from aiogram import Bot
from aiogram.client.session import aiohttp
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, Message
from dotenv import load_dotenv
from google.cloud import storage

from bot.keyboards import *
from bot.states import States
from common.models import Profile
from common.user_service import user_service
from texts.text_manager import MessageText, resource_manager, translate

logger = loguru.logger
load_dotenv()
bot = Bot(os.environ.get("BOT_TOKEN"))
BACKEND_URL = os.environ.get("BACKEND_URL")


async def show_profile_editing_menu(message: Message, profile: Profile, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(lang=profile.language)

    if profile.status == "client":
        questionnaire = user_service.storage.get_client_by_id(profile.id)
        reply_markup = edit_client_profile(profile.language) if questionnaire else None
        state_to_set = States.edit_profile if questionnaire else States.gender
        response_message = MessageText.choose_profile_parameter if questionnaire else MessageText.edit_profile
    else:
        questionnaire = user_service.storage.get_coach_by_id(profile.id)
        reply_markup = edit_coach_profile(profile.language) if questionnaire else None
        state_to_set = States.edit_profile if questionnaire else States.name
        response_message = MessageText.choose_profile_parameter if questionnaire else MessageText.edit_profile

    await message.answer(text=translate(response_message, lang=profile.language), reply_markup=reply_markup)
    await state.set_state(state_to_set)

    if not questionnaire:
        if profile.status == "client":
            await message.answer(
                translate(MessageText.choose_gender, lang=profile.language),
                reply_markup=choose_gender(profile.language),
            )
        else:
            await message.answer(translate(MessageText.name, lang=profile.language))
    with suppress(TelegramBadRequest):
        await message.delete()


async def show_main_menu(message: Message, profile: Profile, state: FSMContext) -> None:
    menu = client_menu_keyboard if profile.status == "client" else coach_menu_keyboard
    await state.clear()
    await state.set_state(States.main_menu)
    await state.update_data(profile=Profile.to_dict(profile))
    if profile.status == "coach":
        coach = user_service.storage.get_coach_by_id(profile.id)
        if not coach or not coach.verified:
            await message.answer(translate(MessageText.coach_info_message, lang=profile.language))
    await message.answer(
        text=translate(MessageText.main_menu, lang=profile.language), reply_markup=menu(profile.language)
    )
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
    profile_data = await user_service.get_profile_by_username(data["username"])
    user_service.storage.set_profile(
        profile=profile_data,
        username=data["username"],
        auth_token=token,
        telegram_id=message.from_user.id,
        email=message.text,
    )
    await message.answer(text=translate(MessageText.registration_successful, lang=data["lang"]))
    profile = user_service.storage.get_current_profile(message.from_user.id)
    await show_main_menu(message, profile, state)


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
    profile = await user_service.get_profile_by_username(data["username"])
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
    await show_main_menu(message, profile, state)
    with suppress(TelegramBadRequest):
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


async def update_user_info(message: Message, state: FSMContext, role: str) -> None:
    data = await state.get_data()
    try:
        profile = user_service.storage.get_current_profile(message.chat.id)
        if not profile:
            raise ValueError("Profile not found")

        if role == "client":
            user_service.storage.set_client_data(profile.id, data)
        else:
            if not data.get("edit_mode"):
                await notify_about_new_coach(message.from_user.id, profile, data)  # TODO: IMPLEMENT
            user_service.storage.set_coach_data(profile.id, data)

        token = user_service.storage.get_profile_info_by_key(message.chat.id, profile.id, "auth_token")
        if not token:
            raise ValueError("Authentication token not found")

        await user_service.edit_profile(profile.id, data, token)
        await message.answer(translate(MessageText.your_data_updated, lang=data["lang"]))
        await state.clear()
        await state.update_data(profile=Profile.to_dict(profile))
        await state.set_state(States.main_menu)

        reply_markup = client_menu_keyboard(data["lang"]) if role == "client" else coach_menu_keyboard(data["lang"])
        await message.answer(translate(MessageText.main_menu, lang=data["lang"]), reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error updating profile: {e}")
        await message.answer(translate(MessageText.unexpected_error, lang=data["lang"]))

    finally:
        await message.delete()


async def notify_about_new_coach(tg_id: int, profile: Profile, data: dict[str, Any]) -> None:
    pass

