from typing import cast

from loguru import logger
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from config.env_settings import Settings
from core.cache import Cache
from core.exceptions import ProfileNotFoundError
from core.services import APIService
from bot.functions import menus
from bot.functions.chat import send_coach_request
from bot.functions.utils import delete_messages, del_msg, answer_msg
from core.models import Client, Coach, Profile
from bot.texts.text_manager import msg_text


async def update_profile_data(message: Message, state: FSMContext, status: str) -> None:
    data = await state.get_data()
    await delete_messages(state)

    try:
        profile = await get_user_profile(message.chat.id)
        if not profile:
            raise ValueError("Profile not found")

        user_data = {**data, "id": profile.id}
        if status == "client":
            if data.get("edit_mode"):
                await Cache.client.update_client(profile.id, user_data)
            else:
                await Cache.client.save_client(profile.id, user_data)
            await APIService.profile.update_client_profile(profile.id, user_data)

        else:
            if not data.get("edit_mode"):
                if message.from_user:
                    await answer_msg(
                        message, msg_text("wait_for_verification", data.get("lang", Settings.DEFAULT_LANG))
                    )
                    await send_coach_request(message.from_user.id, profile, data)
                    await Cache.coach.save_coach(profile.id, user_data)
            else:
                await Cache.coach.update_coach(profile.id, user_data)
            await APIService.profile.update_coach_profile(profile.id, user_data)

        await answer_msg(message, msg_text("your_data_updated", data.get("lang", Settings.DEFAULT_LANG)))
        await menus.show_main_menu(message, profile, state)

    except Exception as e:
        logger.error(f"Unexpected error updating profile: {e}")
        await answer_msg(message, msg_text("unexpected_error", data.get("lang", Settings.DEFAULT_LANG)))

    finally:
        await del_msg(cast(Message | CallbackQuery | None, message))


async def assign_coach(coach: Coach, client: Client) -> None:
    coach_clients = coach.assigned_to or []
    if client.id not in coach_clients:
        coach_clients.append(client.id)
        await APIService.profile.update_coach_profile(coach.id, {"assigned_to": coach_clients})
        await Cache.coach.update_coach(coach.id, {"assigned_to": coach_clients})

    await APIService.profile.update_client_profile(client.id, {"assigned_to": [coach.id]})
    await Cache.client.update_client(client.id, {"assigned_to": [coach.id]})


async def check_assigned_clients(profile_id: int) -> bool:
    coach = await Cache.coach.get_coach(profile_id)
    if not coach:
        return False
    assigned_clients = coach.assigned_to or []

    for client_id in assigned_clients:
        subscription = await Cache.workout.get_subscription(client_id)
        waiting_program = await Cache.workout.check_payment_status(client_id, "program")
        if subscription and subscription.enabled or waiting_program:
            return True

    return False


async def get_user_profile(telegram_id: int) -> Profile | None:
    try:
        return await Cache.profile.get_profile(telegram_id)
    except ProfileNotFoundError:
        if profile := await APIService.profile.get_profile_by_tg_id(telegram_id):
            await Cache.profile.update_profile(telegram_id, profile.model_dump())
            return profile
    return None
