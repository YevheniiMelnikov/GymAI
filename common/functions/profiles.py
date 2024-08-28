from contextlib import suppress

import loguru
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import client_menu_keyboard, coach_menu_keyboard
from bot.states import States
from common.backend_service import backend_service
from common.exceptions import UserServiceError
from common.functions.chat import notify_about_new_coach
from common.functions.menus import show_main_menu
from common.functions.utils import delete_messages
from common.models import Client, Coach, Profile
from texts.text_manager import MessageText, translate

logger = loguru.logger


async def update_user_info(message: Message, state: FSMContext, role: str) -> None:
    data = await state.get_data()
    data["tg_id"] = message.from_user.id
    await delete_messages(state)
    try:
        profile = backend_service.cache.get_current_profile(message.chat.id)
        if not profile:
            raise ValueError("Profile not found")

        if role == "client":
            backend_service.cache.set_client_data(str(profile.id), data)
        else:
            if not data.get("edit_mode"):
                await message.answer(translate(MessageText.wait_for_verification, data.get("lang")))
                await notify_about_new_coach(message.from_user.id, profile, data)
            backend_service.cache.set_coach_data(str(profile.id), data)

        token = backend_service.cache.get_profile_info_by_key(message.chat.id, profile.id, "auth_token")
        if not token:
            token = await backend_service.get_user_token(profile.id)

        await backend_service.edit_profile(profile.id, data, token)
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
        backend_service.cache.set_coach_data(str(coach.id), {"assigned_to": coach_clients})

    backend_service.cache.set_client_data(str(client.id), {"assigned_to": [int(coach.id)]})
    token = backend_service.cache.get_profile_info_by_key(client.tg_id, client.id, "auth_token")
    if not token:
        token = await backend_service.get_user_token(client.id)
    await backend_service.edit_profile(client.id, {"assigned_to": [coach.id]}, token)
    await backend_service.edit_profile(coach.id, {"assigned_to": coach_clients}, token)


async def sign_in(message: Message, state: FSMContext, data: dict) -> None:
    token = await backend_service.log_in(username=data["username"], password=message.text)
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
    profile = await backend_service.get_profile_by_username(data["username"])
    if not profile:
        await message.answer(text=translate(MessageText.unexpected_error, lang=data.get("lang")))
        await state.set_state(States.username)
        await message.answer(text=translate(MessageText.username, lang=data.get("lang")))
        await message.delete()
        return

    await state.update_data(login_attempts=0)
    email = await backend_service.get_user_email(profile.id)
    backend_service.cache.set_profile(
        profile=profile, username=data["username"], auth_token=token, telegram_id=str(message.from_user.id), email=email
    )
    logger.info(f"profile_id {profile.id} set for user {message.from_user.id}")
    await backend_service.edit_profile(profile_id=profile.id, data={"current_tg_id": message.from_user.id}, token=token)
    logger.info(f"tg_id {message.from_user.id} set for profile_id {profile.id}")

    if profile.status == "coach":
        try:
            backend_service.cache.get_coach_by_id(profile.id)
        except UserServiceError:
            coach_data = await backend_service.get_profile_data(profile.id)
            coach_data["tg_id"] = message.from_user.id
            backend_service.cache.set_coach_data(profile.id, coach_data)
    else:
        try:
            backend_service.cache.get_client_by_id(profile.id)
        except UserServiceError:
            client_data = await backend_service.get_profile_data(profile.id)
            client_data["tg_id"] = message.from_user.id
            backend_service.cache.set_client_data(profile.id, client_data)

    await message.answer(text=translate(MessageText.signed_in, lang=data.get("lang")))
    await delete_messages(state)
    if data.get("lang") != profile.language:
        backend_service.cache.set_profile_info_by_key(message.from_user.id, profile.id, "language", data.get("lang"))
        profile.language = data.get("lang")
    await show_main_menu(message, profile, state)
    with suppress(TelegramBadRequest):
        await message.delete()


async def register_user(callback_query: CallbackQuery, state: FSMContext, data: dict) -> None:
    email = data.get("email")
    username = data.get("username")
    password = data.get("password")

    if not await backend_service.sign_up(
        current_tg_id=callback_query.from_user.id,
        username=username,
        password=password,
        email=email,
        status=data.get("account_type"),
        language=data.get("lang"),
    ):
        logger.error(f"Registration failed for user {callback_query.from_user.id}")
        await callback_query.message.answer(text=translate(MessageText.unexpected_error, data.get("lang")))
        await state.clear()
        await state.set_state(States.username)
        await callback_query.message.answer(text=translate(MessageText.username, data.get("lang")))
        return

    logger.info(f"User {email} registered successfully.")
    token = await backend_service.log_in(username=username, password=password)

    if not token:
        logger.error(f"Login failed for user {username} after registration")
        await callback_query.message.answer(text=translate(MessageText.unexpected_error, data.get("lang")))
        await state.clear()
        await state.set_state(States.username)
        await callback_query.message.answer(text=translate(MessageText.username, data.get("lang")))
        return

    profile_data = await backend_service.get_profile_by_username(username)
    logger.info(f"User {profile_data.id} logged in")
    backend_service.cache.set_profile(
        profile=profile_data,
        username=username,
        auth_token=token,
        telegram_id=str(callback_query.from_user.id),
        email=email,
    )
    await callback_query.message.answer(text=translate(MessageText.registration_successful, lang=data.get("lang")))
    await show_main_menu(callback_query.message, profile_data, state)


async def check_assigned_clients(profile_id: int) -> bool:
    coach = backend_service.cache.get_coach_by_id(profile_id)
    assigned_clients = coach.assigned_to
    for client in assigned_clients:
        subscription = backend_service.cache.get_subscription(client.id)
        waiting_program = backend_service.cache.check_payment_status(client.id, "program")
        if subscription.enabled or waiting_program:
            return True

    return False
