from contextlib import suppress

import loguru
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import action_choice_keyboard
from bot.states import States
from services.backend_service import backend_service
from common.cache_manager import cache_manager
from common.exceptions import ProfileNotFoundError, UserServiceError
from common.functions import chat, menus
from common.functions.utils import delete_messages
from common.models import Client, Coach, Profile
from services.profile_service import profile_service
from services.user_service import user_service
from texts.resources import MessageText
from texts.text_manager import translate

logger = loguru.logger


async def update_user_info(message: Message, state: FSMContext, role: str) -> None:
    data = await state.get_data()
    await delete_messages(state)
    try:
        profile = await get_or_load_profile(message.chat.id)
        if not profile:
            raise ValueError("Profile not found")

        token = cache_manager.get_profile_info_by_key(message.chat.id, profile.id, "auth_token")
        if not token:
            token = await user_service.get_user_token(profile.id)

        if role == "client":
            cache_manager.set_client_data(profile.id, data)
            await profile_service.edit_client_profile(profile.id, data, token)
        else:
            if not data.get("edit_mode"):
                await message.answer(translate(MessageText.wait_for_verification, data.get("lang")))
                await chat.notify_about_new_coach(message.from_user.id, profile, data)
            cache_manager.set_coach_data(profile.id, data)
            await profile_service.edit_coach_profile(profile.id, data, token)

        await message.answer(translate(MessageText.your_data_updated, lang=data.get("lang")))
        await menus.show_main_menu(message, profile, state)

    except Exception as e:
        logger.error(f"Unexpected error updating profile: {e}")
        await message.answer(translate(MessageText.unexpected_error, lang=data.get("lang")))
    finally:
        with suppress(TelegramBadRequest):
            await message.delete()


async def assign_coach(coach: Coach, client: Client, telegram_id: int) -> None:
    coach_clients = coach.assigned_to if isinstance(coach.assigned_to, list) else []
    if client.id not in coach_clients:
        coach_clients.append(int(client.id))
        cache_manager.set_coach_data(coach.id, {"assigned_to": coach_clients})

    cache_manager.set_client_data(client.id, {"assigned_to": [coach.id]})
    token = cache_manager.get_profile_info_by_key(telegram_id, client.id, "auth_token")
    if not token:
        token = await user_service.get_user_token(client.id)
    await profile_service.edit_client_profile(client.id, {"assigned_to": [coach.id]}, token)
    await profile_service.edit_coach_profile(coach.id, {"assigned_to": coach_clients}, token)


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

    profile = await profile_service.get_profile_by_username(data["username"])
    logger.info(f"Telegram user {message.from_user.id} logged in with profile_id {profile.id}")

    if not profile:
        await message.answer(text=translate(MessageText.unexpected_error, lang=data.get("lang")))
        await state.set_state(States.username)
        await message.answer(text=translate(MessageText.username, lang=data.get("lang")))
        await message.delete()
        return

    await state.update_data(login_attempts=0)
    email = await user_service.get_user_email(profile.id)
    cache_manager.set_profile(
        profile=profile, username=data["username"], auth_token=token, telegram_id=message.from_user.id, email=email
    )
    await profile_service.reset_telegram_id(profile.id, message.from_user.id)
    logger.debug(f"profile_id {profile.id} set for user {message.from_user.id}")
    await profile_service.edit_profile(profile_id=profile.id, data={"current_tg_id": message.from_user.id}, token=token)

    if profile.status == "coach":
        try:
            cache_manager.get_coach_by_id(profile.id)
        except UserServiceError:
            coach_data = await profile_service.get_profile(profile.id)
            cache_manager.set_coach_data(profile.id, coach_data)
    else:
        try:
            cache_manager.get_client_by_id(profile.id)
        except UserServiceError:
            client_data = await profile_service.get_profile(profile.id)
            cache_manager.set_client_data(profile.id, client_data)

    await message.answer(text=translate(MessageText.signed_in, lang=data.get("lang")))
    await delete_messages(state)
    if data.get("lang") != profile.language:
        cache_manager.set_profile_info_by_key(message.from_user.id, profile.id, "language", data.get("lang"))
        profile.language = data.get("lang")
    await menus.show_main_menu(message, profile, state)
    with suppress(TelegramBadRequest):
        await message.delete()


async def register_user(callback_query: CallbackQuery, state: FSMContext, data: dict) -> None:
    email = data.get("email")
    username = data.get("username")
    password = data.get("password")

    if not await user_service.sign_up(
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
    token = await user_service.log_in(username=username, password=password)

    if not token:
        logger.error(f"Login failed for user {username} after registration")
        await callback_query.message.answer(text=translate(MessageText.unexpected_error, data.get("lang")))
        await state.clear()
        await state.set_state(States.username)
        await callback_query.message.answer(text=translate(MessageText.username, data.get("lang")))
        return

    profile_data = await profile_service.get_profile_by_username(username)
    assert profile_data
    logger.info(f"User {profile_data.id} logged in")
    await profile_service.reset_telegram_id(profile_data.id, callback_query.from_user.id)
    cache_manager.set_profile(
        profile=profile_data,
        username=username,
        auth_token=token,
        telegram_id=callback_query.from_user.id,
        email=email,
    )
    if not await backend_service.send_welcome_email(email=email, username=username):
        logger.error(f"Failed to send welcome email to {email}")
    await callback_query.message.answer(text=translate(MessageText.registration_successful, lang=data.get("lang")))
    await menus.show_main_menu(callback_query.message, profile_data, state)


async def check_assigned_clients(profile_id: int) -> bool:
    coach = cache_manager.get_coach_by_id(profile_id)
    assigned_clients = coach.assigned_to
    for client in assigned_clients:
        subscription = cache_manager.get_subscription(client.id)
        waiting_program = cache_manager.check_payment_status(client.id, "program")
        if subscription.enabled or waiting_program:
            return True

    return False


async def get_or_load_profile(telegram_id: int) -> Profile | None:
    try:
        return cache_manager.get_current_profile(telegram_id)
    except ProfileNotFoundError:
        profile_data = await profile_service.get_profile_by_telegram_id(telegram_id)
        if profile_data:
            profile = Profile.from_dict(profile_data)
            await profile_service.reset_telegram_id(profile.id, telegram_id)
            token = await user_service.get_user_token(profile.id)
            cache_manager.set_profile(
                profile=profile,
                username=profile_data.get("username", ""),
                auth_token=token,
                telegram_id=telegram_id,
                email=profile_data.get("email", ""),
                is_current=True,
            )
            return profile
        else:
            return None


async def handle_logout(callback_query, profile, state):
    await callback_query.answer("🏃")
    auth_token = cache_manager.get_profile_info_by_key(callback_query.message.from_user.id, profile.id, "auth_token")
    await user_service.log_out(profile, auth_token)
    cache_manager.deactivate_profiles(profile.current_tg_id)
    await state.update_data(lang=profile.language)
    await callback_query.message.answer(
        text=translate(MessageText.choose_action, lang=profile.language),
        reply_markup=action_choice_keyboard(profile.language),
    )
    await state.set_state(States.action_choice)
    await callback_query.message.delete()
