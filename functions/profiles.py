from contextlib import suppress

from common.logger import logger
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import action_choice_kb
from bot.states import States
from services.api_service import APIClient
from core.cache_manager import CacheManager
from core.exceptions import ProfileNotFoundError, UserServiceError
from functions import menus
from functions import chat
from functions.utils import delete_messages
from core.models import Client, Coach, Profile
from services.profile_service import ProfileService
from services.user_service import user_service
from bot.texts.text_manager import msg_text


async def update_user_info(message: Message, state: FSMContext, role: str) -> None:
    data = await state.get_data()
    await delete_messages(state)
    try:
        profile = await get_or_load_profile(message.chat.id)
        if not profile:
            raise ValueError("Profile not found")

        profile_data = {key: data[key] for key in ["name", "assigned_to"] if key in data}
        if profile_data:
            await ProfileService.edit_profile(profile.id, profile_data)

        if role == "client":
            CacheManager.set_client_data(profile.id, data)
            await ProfileService.edit_client_profile_kb(profile.id, data)
        else:
            if not data.get("edit_mode"):
                await message.answer(msg_text("wait_for_verification", data.get("lang")))
                await chat.notify_about_new_coach(message.from_user.id, profile, data)
            CacheManager.set_coach_data(profile.id, data)
            await ProfileService.edit_coach_profile_kb(profile.id, data)

        await message.answer(msg_text("your_data_updated", data.get("lang")))
        await message.answer(msg_text("your_data_updated", data.get("lang")))
        await menus.show_main_menu(message, profile, state)

    except Exception as e:
        logger.error(f"Unexpected error updating profile: {e}")
        await message.answer(msg_text("unexpected_error", data.get("lang")))
    finally:
        with suppress(TelegramBadRequest):
            await message.delete()


async def assign_coach(coach: Coach, client: Client) -> None:
    coach_clients = coach.assigned_to if isinstance(coach.assigned_to, list) else []
    if client.id not in coach_clients:
        coach_clients.append(int(client.id))
        CacheManager.set_coach_data(coach.id, {"assigned_to": coach_clients})
        await ProfileService.edit_profile(coach.id, {"assigned_to": coach_clients})

    coach_profile = await ProfileService.get_coach_profile(coach.id)
    coach_profile_id = int(coach_profile["id"])
    await ProfileService.edit_client_profile(client.id, dict(coach=coach_profile_id))
    CacheManager.set_client_data(client.id, {"assigned_to": [coach.id]})
    await ProfileService.edit_profile(client.id, {"assigned_to": [coach.id]})


async def sign_in(message: Message, state: FSMContext, data: dict) -> None:
    if not await user_service.log_in(username=data["username"], password=message.text):
        attempts = data.get("login_attempts", 0) + 1
        await state.update_data(login_attempts=attempts)
        if attempts >= 3:
            await message.answer(msg_text("reset_password_offer", data.get("lang")))
        else:
            await message.answer(msg_text("invalid_credentials", data.get("lang")))
            await state.set_state(States.username)
            await message.answer(msg_text("username", data.get("lang")))
        await message.delete()
        return

    profile = await ProfileService.get_profile_by_username(data["username"])

    if not profile:
        await message.answer(msg_text("unexpected_error", data.get("lang")))
        await state.set_state(States.username)
        await message.answer(msg_text("username", data.get("lang")))
        await message.delete()
        return

    logger.info(f"Telegram user {message.from_user.id} logged in with profile_id {profile.id}")
    await state.update_data(login_attempts=0)
    try:
        email = await user_service.get_user_email(profile.id)
    except Exception as e:
        logger.error(f"Error retrieving email for profile {profile.id}: {e}")
        email = None
    CacheManager.set_profile(profile=profile, username=data["username"], telegram_id=message.from_user.id, email=email)
    await ProfileService.reset_telegram_id(profile.id, message.from_user.id)
    logger.debug(f"profile_id {profile.id} set for user {message.from_user.id}")
    await ProfileService.edit_profile(profile_id=profile.id, data={"current_tg_id": message.from_user.id})

    if profile.status == "coach":
        try:
            CacheManager.get_coach_by_id(profile.id)
        except UserServiceError:
            coach_data = await ProfileService.get_profile(profile.id)
            CacheManager.set_coach_data(profile.id, coach_data)
    else:
        try:
            CacheManager.get_client_by_id(profile.id)
        except UserServiceError:
            client_data = await ProfileService.get_profile(profile.id)
            CacheManager.set_client_data(profile.id, client_data)

    await message.answer(msg_text("signed_in", data.get("lang")))
    await delete_messages(state)
    if data.get("lang") != profile.language:
        CacheManager.set_profile_info_by_key(message.from_user.id, profile.id, "language", data.get("lang"))
        profile.language = data.get("lang")
    await menus.show_main_menu(message, profile, state)
    with suppress(TelegramBadRequest):
        try:
            await message.delete()
        except TelegramBadRequest as e:
            logger.warning(f"Failed to delete message for user {message.from_user.id}: {e}")


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
        await callback_query.message.answer(msg_text("unexpected_error", data.get("lang")))
        await state.clear()
        await state.set_state(States.username)
        await callback_query.message.answer(msg_text("username", data.get("lang")))
        return

    logger.info(f"User {email} registered successfully")

    if not await user_service.log_in(username=username, password=password):
        await callback_query.message.answer(msg_text("unexpected_error", data.get("lang")))
        await state.clear()
        await state.set_state(States.username)
        await callback_query.message.answer(msg_text("username", data.get("lang")))
        return

    profile_data = await ProfileService.get_profile_by_username(username)
    assert profile_data
    logger.info(f"User {profile_data.id} logged in")
    await ProfileService.reset_telegram_id(profile_data.id, callback_query.from_user.id)
    CacheManager.set_profile(
        profile=profile_data,
        username=username,
        telegram_id=callback_query.from_user.id,
        email=email,
    )
    if not await APIClient.send_welcome_email(email=email, username=username):
        logger.error(f"Failed to send welcome email to {email}")
    await callback_query.message.answer(msg_text("registration_successful", data.get("lang")))
    await menus.show_main_menu(callback_query.message, profile_data, state)


async def check_assigned_clients(profile_id: int) -> bool:
    coach = CacheManager.get_coach_by_id(profile_id)
    assigned_clients = coach.assigned_to
    for client_id in assigned_clients:
        subscription = CacheManager.get_subscription(client_id)
        waiting_program = CacheManager.check_payment_status(client_id, "program")
        if subscription.enabled or waiting_program:
            return True

    return False


async def get_or_load_profile(telegram_id: int) -> Profile | None:
    try:
        return CacheManager.get_current_profile(telegram_id)
    except ProfileNotFoundError:
        try:
            if profile_data := await ProfileService.get_profile_by_telegram_id(telegram_id):
                profile = Profile.from_dict(profile_data)
                await ProfileService.reset_telegram_id(profile.id, telegram_id)
                user_data = profile_data.get("user", {})

                CacheManager.set_profile(
                    profile=profile,
                    username=user_data.get("username", ""),
                    telegram_id=telegram_id,
                    email=user_data.get("email", ""),
                    is_current=True,
                )
                return profile

        except Exception as e:
            logger.error(f"Error occurred while fetching profile for user {telegram_id} from database: {e}")


async def handle_logout(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    await callback_query.answer("🏃")
    auth_token = await user_service.get_user_token(profile.id)
    await user_service.log_out(profile, auth_token)
    CacheManager.deactivate_profiles(profile.current_tg_id)
    await state.update_data(profile.language)
    await callback_query.message.answer(
        msg_text("select_action", profile.language),
        reply_markup=action_choice_kb(profile.language),
    )
    await state.set_state(States.action_choice)
    await callback_query.message.delete()


async def start_profile_creation(message: Message, profile: Profile, state: FSMContext) -> None:
    info_msg = await message.answer(msg_text("edit_profile", profile.language))
    name_msg = await message.answer(msg_text("name", profile.language))
    await state.update_data(
        profile.language,
        role=profile.status,
        chat_id=message.chat.id,
        message_ids=[info_msg.message_id, name_msg.message_id],
    )
    await state.set_state(States.name)
    with suppress(TelegramBadRequest):
        await message.delete()
