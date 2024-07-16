from contextlib import suppress

import loguru
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import client_menu_keyboard, coach_menu_keyboard
from bot.states import States
from common.functions.chat import notify_about_new_coach
from common.functions.menus import show_main_menu
from common.models import Client, Coach, Profile
from common.user_service import user_service
from texts.text_manager import MessageText, translate

logger = loguru.logger


async def update_user_info(message: Message, state: FSMContext, role: str) -> None:
    data = await state.get_data()
    data["tg_id"] = message.from_user.id
    try:
        profile = user_service.storage.get_current_profile(message.chat.id)
        if not profile:
            raise ValueError("Profile not found")

        if role == "client":
            user_service.storage.set_client_data(str(profile.id), data)
        else:
            if not data.get("edit_mode"):
                await message.answer(translate(MessageText.wait_for_verification, data.get("lang")))
                await notify_about_new_coach(message.from_user.id, profile, data)
            user_service.storage.set_coach_data(str(profile.id), data)

        token = user_service.storage.get_profile_info_by_key(message.chat.id, profile.id, "auth_token")
        if not token:
            raise ValueError("Authentication token not found")

        await user_service.edit_profile(profile.id, data, token)
        await message.answer(translate(MessageText.your_data_updated, lang=data.get("lang")))
        await state.clear()
        await state.update_data(profile=Profile.to_dict(profile))
        await state.set_state(States.main_menu)

        reply_markup = (
            client_menu_keyboard(data.get("lang")) if role == "client" else coach_menu_keyboard(data.get("lang"))
        )
        await message.answer(translate(MessageText.main_menu, lang=data.get("lang")), reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Unexpected error updating profile: {e}")
        await message.answer(translate(MessageText.unexpected_error, lang=data.get("lang")))
    finally:
        await message.delete()


async def assign_coach(coach: Coach, client: Client) -> None:
    coach_clients = coach.assigned_to if isinstance(coach.assigned_to, list) else []
    if client.id not in coach_clients:
        coach_clients.append(int(client.id))
        user_service.storage.set_coach_data(str(coach.id), {"assigned_to": coach_clients})

    user_service.storage.set_client_data(str(client.id), {"assigned_to": [int(coach.id)]})
    token = user_service.storage.get_profile_info_by_key(client.tg_id, client.id, "auth_token")
    await user_service.edit_profile(client.id, {"assigned_to": [coach.id]}, token)
    await user_service.edit_profile(coach.id, {"assigned_to": coach_clients}, token)


async def sign_in(message: Message, state: FSMContext, data: dict) -> None:
    token = await user_service.log_in(username=data["username"], password=message.text)
    if not token:
        attempts = data.get("login_attempts", 0) + 1
        await state.update_data(login_attempts=attempts)
        if attempts >= 3:
            await message.answer(text=translate(MessageText.reset_password_offer, lang=data.get("lang")))
        else:
            await message.answer(text=translate(MessageText.invalid_credentials, lang=data.get("lang")))
            await state.set_state(States.username)
            await message.answer(text=translate(MessageText.username, lang=data.get("lang")))
        await message.delete()
        return

    logger.info(f"User {message.from_user.id} logged in")
    profile = await user_service.get_profile_by_username(data["username"])
    if not profile:
        await message.answer(text=translate(MessageText.unexpected_error, lang=data.get("lang")))
        await state.set_state(States.username)
        await message.answer(text=translate(MessageText.username, lang=data.get("lang")))
        await message.delete()
        return

    await state.update_data(login_attempts=0)
    user_service.storage.set_profile(
        profile=profile, username=data["username"], auth_token=token, telegram_id=str(message.from_user.id)
    )
    logger.info(f"profile_id {profile.id} set for user {message.from_user.id}")
    await message.answer(text=translate(MessageText.signed_in, lang=data.get("lang")))
    await show_main_menu(message, profile, state)
    with suppress(TelegramBadRequest):
        await message.delete()


async def register_user(message: Message, state: FSMContext, data: dict) -> None:
    email = data.get("email")
    if not await user_service.sign_up(
        username=data.get("username"),
        password=data.get("password"),
        email=email,
        status=data.get("account_type"),
        language=data.get("lang"),
    ):
        logger.error(f"Registration failed for user {message.from_user.id}")
        await message.answer(text=translate(MessageText.unexpected_error, data.get("lang")))
        await state.clear()
        await state.set_state(States.username)
        await message.answer(text=translate(MessageText.username, data.get("lang")))
        return

    logger.info(f"User {email} registered")
    token = await user_service.log_in(username=data.get("username"), password=data.get("password"))

    if not token:
        logger.error(f"Login failed for user {email} after registration")
        await message.answer(text=translate(MessageText.unexpected_error, data.get("lang")))
        await state.clear()
        await state.set_state(States.username)
        await message.answer(text=translate(MessageText.username, data.get("lang")))
        return

    profile_data = await user_service.get_profile_by_username(data.get("username"))
    logger.info(f"User {profile_data.id} logged in")
    user_service.storage.set_profile(
        profile=profile_data,
        username=data.get("username"),
        auth_token=token,
        telegram_id=str(message.from_user.id),
        email=email,
    )
    await message.answer(text=translate(MessageText.registration_successful, lang=data.get("lang")))
    profile = user_service.storage.get_current_profile(message.from_user.id)
    await show_main_menu(message, profile, state)
