from datetime import datetime, timedelta
from typing import cast

from loguru import logger
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.exceptions import TelegramBadRequest
from pathlib import Path

from bot.keyboards import profile_menu_kb
from config.env_settings import settings
from core.cache import Cache
from core.enums import ClientStatus, CoachType
from core.exceptions import (
    CoachNotFoundError,
    SubscriptionNotFoundError,
    ClientNotFoundError,
)
from core.services import APIService
from bot.utils import menus
from bot.utils.chat import send_coach_request
from bot.utils.other import delete_messages, del_msg, answer_msg
from core.schemas import Client, Coach, Profile
from bot.texts.text_manager import msg_text
from core.services.outer import avatar_manager


async def update_profile_data(message: Message, state: FSMContext, role: str, bot: Bot) -> None:
    data = await state.get_data()
    await delete_messages(state)

    try:
        profile = await Cache.profile.get_profile(message.chat.id)
        assert profile is not None

        user_data = {**data}
        user_data.pop("profile", None)

        if role == "client":
            if data.get("status") != ClientStatus.initial:
                client = await Cache.client.get_client(profile.id)
                await Cache.client.update_client(client.id, user_data)
                await APIService.profile.update_client_profile(client.id, user_data)
            else:
                if client := await APIService.profile.create_client_profile(profile.id, user_data):
                    await Cache.client.save_client(profile.id, client.model_dump())
                    await answer_msg(
                        message, msg_text("initial_credits_granted", data.get("lang", settings.DEFAULT_LANG))
                    )
                else:
                    await Cache.client.save_client(profile.id, {"profile": profile.id, **user_data})
        else:
            if data.get("edit_mode"):
                coach = await Cache.coach.get_coach(profile.id)
                await Cache.coach.update_coach(profile.id, user_data)
                await APIService.profile.update_coach_profile(coach.id, user_data)
            else:
                if message.from_user:
                    await answer_msg(
                        message, msg_text("wait_for_verification", data.get("lang", settings.DEFAULT_LANG))
                    )
                    await send_coach_request(message.from_user.id, profile, data, bot)
                    if coach := await APIService.profile.create_coach_profile(profile.id, user_data):
                        await Cache.coach.save_coach(profile.id, coach.model_dump())
                    else:
                        await Cache.coach.save_coach(profile.id, {"profile": profile.id, **user_data})

        await answer_msg(message, msg_text("your_data_updated", data.get("lang", settings.DEFAULT_LANG)))
        await menus.show_main_menu(message, profile, state)

    except Exception as e:
        logger.error(f"Unexpected error updating profile: {e}")
        await answer_msg(message, msg_text("unexpected_error", data.get("lang", settings.DEFAULT_LANG)))

    finally:
        await del_msg(cast(Message | CallbackQuery | None, message))


async def assign_coach(coach: Coach, client: Client) -> None:
    coach_clients = coach.assigned_to or []
    if client.id not in coach_clients:
        coach_clients.append(client.id)
        await APIService.profile.update_coach_profile(coach.id, {"assigned_to": coach_clients})
        await Cache.coach.update_coach(coach.profile, {"assigned_to": coach_clients})

    await APIService.profile.update_client_profile(client.id, {"assigned_to": [coach.id]})
    await Cache.client.update_client(client.id, {"assigned_to": [coach.id]})


async def check_assigned_clients(profile_id: int) -> bool:
    try:
        coach = await Cache.coach.get_coach(profile_id)
    except CoachNotFoundError:
        logger.info(f"Coach not found for profile_id {profile_id} in check_assigned_clients.")
        return False

    assigned_clients = coach.assigned_to or []

    for client_id in assigned_clients:
        try:
            subscription = await Cache.workout.get_latest_subscription(client_id)
            if subscription.enabled:
                return True
        except SubscriptionNotFoundError:
            pass

        if await Cache.payment.get_status(client_id, "program"):
            return True

    return False


async def fetch_user(profile: Profile) -> Client | Coach:
    if profile.role == "client":
        try:
            return await Cache.client.get_client(profile.id)
        except ClientNotFoundError:
            logger.error(
                f"ClientNotFoundError for an existing profile {profile.id}. This might indicate data inconsistency."
            )
            raise ValueError(f"Client data not found for existing profile id {profile.id}")

    elif profile.role == "coach":
        try:
            return await Cache.coach.get_coach(profile.id)
        except CoachNotFoundError:
            logger.error(
                f"CoachNotFoundError for an existing profile {profile.id}. This might indicate data inconsistency."
            )
            raise ValueError(f"Coach data not found for existing profile id {profile.id}")
    else:
        raise ValueError(f"Unknown profile role: {profile.role}")


async def answer_profile(cbq: CallbackQuery, profile: Profile, user: Coach | Client, text: str) -> None:
    message = cbq.message
    if not isinstance(message, Message):
        return

    if profile.role == "coach" and isinstance(user, Coach):
        if user.coach_type == CoachType.ai or not user.profile_photo:
            file_path = Path(__file__).resolve().parent.parent / "images" / "ai_coach.png"
            if file_path.exists():
                avatar = FSInputFile(file_path)
                try:
                    await message.answer_photo(avatar, text, reply_markup=profile_menu_kb(profile.language))
                    return
                except TelegramBadRequest:
                    logger.warning("Photo not found for AI coach")
        else:
            photo_url = f"https://storage.googleapis.com/{avatar_manager.bucket_name}/{user.profile_photo}"
            try:
                await message.answer_photo(photo_url, text, reply_markup=profile_menu_kb(profile.language))
                return
            except TelegramBadRequest:
                logger.warning("Photo not found for coach %s", profile.id)

    if profile.role == "client" and isinstance(user, Client):
        if user.profile_photo:
            photo_url = f"https://storage.googleapis.com/{avatar_manager.bucket_name}/{user.profile_photo}"
            try:
                await message.answer_photo(photo_url, text, reply_markup=profile_menu_kb(profile.language))
                return
            except TelegramBadRequest:
                logger.warning("Photo not found for client %s", profile.id)

        avatar_name = "male.png" if user.gender != "female" else "female.png"
        file_path = Path(__file__).resolve().parent.parent / "images" / avatar_name

        if file_path.exists():
            avatar_file = FSInputFile(file_path)
            try:
                await message.answer_photo(avatar_file, text, reply_markup=profile_menu_kb(profile.language))
                return
            except TelegramBadRequest as e:
                logger.warning("Failed to send default avatar for client %s: %s", profile.id, e)
        else:
            logger.error("Default avatar file not found: %s", file_path)

    await message.answer(text, reply_markup=profile_menu_kb(profile.language))


async def get_clients_to_survey() -> list[Profile]:
    clients_with_workout: list[Profile] = []

    try:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%A").lower()
        raw_clients = await Cache.client.get_all("clients") or []

        for client_id_str in raw_clients:
            try:
                client_id = int(client_id_str)

                subscription = await Cache.workout.get_latest_subscription(client_id)
                if not subscription:
                    continue

                if not isinstance(subscription.workout_days, list):
                    logger.warning(f"Invalid workout_days format for client_id={client_id}")
                    continue

                if (
                    subscription.enabled
                    and subscription.exercises
                    and yesterday in [day.lower() for day in subscription.workout_days]
                ):
                    client = await Cache.client.get_client(client_id)
                    profile = await APIService.profile.get_profile(client.profile)
                    if profile is not None:
                        clients_with_workout.append(profile)

            except Exception as client_err:
                logger.warning(f"Skipping client_id={client_id_str} due to error: {client_err}")
                continue

    except Exception as e:
        logger.error(f"Failed to load clients for survey: {e}")

    return clients_with_workout
