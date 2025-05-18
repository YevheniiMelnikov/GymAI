from contextlib import suppress

from loguru import logger
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from core.cache import Cache
from core.exceptions import ProfileNotFoundError
from functions import menus
from functions import chat
from functions.utils import delete_messages
from core.models import Client, Coach, Profile
from core.services.profile_service import ProfileService
from bot.texts.text_manager import msg_text


async def update_profile_data(message: Message, state: FSMContext, status: str) -> None:
    data = await state.get_data()
    await delete_messages(state)
    try:
        profile = await get_user_profile(message.chat.id)
        if not profile:
            raise ValueError("Profile not found")

        profile_data = {key: data[key] for key in ["name", "assigned_to"] if key in data}
        if profile_data:
            await ProfileService.edit_profile(profile.id, profile_data)

        if status == "client":
            Cache.client.set_client_data(profile.id, data)
            await ProfileService.edit_client_profile(profile.id, data)
        else:
            if not data.get("edit_mode"):
                await message.answer(msg_text("wait_for_verification", data.get("lang")))
                await chat.send_coach_request(message.from_user.id, profile, data)
            Cache.coach.set_coach_data(profile.id, data)
            await ProfileService.edit_coach_profile(profile.id, data)

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
        Cache.coach.set_coach_data(coach.id, {"assigned_to": coach_clients})
        await ProfileService.edit_profile(coach.id, {"assigned_to": coach_clients})

    coach_profile = await ProfileService.get_coach_profile(coach.id)
    coach_profile_id = int(coach_profile["id"])
    await ProfileService.edit_client_profile(client.id, dict(coach=coach_profile_id))
    Cache.client.set_client_data(client.id, {"assigned_to": [coach.id]})
    await ProfileService.edit_profile(client.id, {"assigned_to": [coach.id]})


async def check_assigned_clients(profile_id: int) -> bool:
    coach = Cache.coach.get_coach(profile_id)
    assigned_clients = coach.assigned_to
    for client_id in assigned_clients:
        subscription = Cache.workout.get_subscription(client_id)
        waiting_program = Cache.workout.check_payment_status(client_id, "program")
        if subscription.enabled or waiting_program:
            return True

    return False


async def get_user_profile(telegram_id: int) -> Profile | None:
    try:
        return Cache.profile.get_profile(telegram_id)
    except ProfileNotFoundError:
        profile = await ProfileService.get_profile_by_tg_id(telegram_id)
        if profile:
            Cache.profile.set_profile_data(telegram_id, profile.to_dict())
            return profile
