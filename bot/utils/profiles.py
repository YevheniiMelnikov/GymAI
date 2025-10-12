from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

from loguru import logger

from bot.texts.text_manager import msg_text
from bot.utils.bot import answer_msg, del_msg, delete_messages
from config.app_settings import settings
from core.cache import Cache
from core.enums import ClientStatus, CoachType
from core.exceptions import (
    ClientNotAssignedError,
    ClientNotFoundError,
    CoachNotFoundError,
    SubscriptionNotFoundError,
)
from core.schemas import Client, Coach, Profile
from core.services import get_avatar_manager
from core.services.internal import APIService

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.fsm.context import FSMContext
    from aiogram.types import Message as TgMessage, CallbackQuery as TgCallbackQuery

_IMAGES_DIR = Path(__file__).resolve().parent.parent / "images"


async def update_profile_data(message: TgMessage, state: FSMContext, role: str, bot: Bot) -> None:
    data = await state.get_data()
    await delete_messages(state)

    try:
        profile = await Cache.profile.get_profile(message.chat.id)
        assert profile is not None

        user_data = {**data}
        user_data.pop("profile", None)

        if role == "client":
            credits_delta = data.pop("credits_delta", 0)
            if data.get("status") != ClientStatus.initial:
                client = await Cache.client.get_client(profile.id)
                if credits_delta:
                    user_data["credits"] = client.credits + credits_delta
                await Cache.client.update_client(client.profile, user_data)
                await APIService.profile.update_client_profile(client.id, user_data)
            else:
                if credits_delta:
                    user_data["credits"] = credits_delta
                client = await APIService.profile.create_client_profile(profile.id, user_data)
                if client is not None:
                    await Cache.client.save_client(profile.id, client.model_dump())
        else:
            if data.get("edit_mode"):
                coach = await Cache.coach.get_coach(profile.id)
                await Cache.coach.update_coach(profile.id, user_data)
                await APIService.profile.update_coach_profile(coach.id, user_data)
            else:
                if message.from_user:
                    await answer_msg(
                        message,
                        msg_text("wait_for_verification", data.get("lang", settings.DEFAULT_LANG)),
                    )
                    from bot.utils.chat import send_coach_request

                    await send_coach_request(message.from_user.id, profile, data, bot)
                    coach = await APIService.profile.create_coach_profile(profile.id, user_data)
                    if coach is not None:
                        await Cache.coach.save_coach(profile.id, coach.model_dump())

        await answer_msg(message, msg_text("your_data_updated", data.get("lang", settings.DEFAULT_LANG)))

        from bot.utils.menus import show_main_menu

        await show_main_menu(message, profile, state)

    except Exception as e:
        logger.error(f"Unexpected error updating profile: {e}")
        await answer_msg(message, msg_text("unexpected_error", data.get("lang", settings.DEFAULT_LANG)))

    finally:
        await del_msg(cast("TgMessage | TgCallbackQuery | None", message))


async def assign_coach(coach: Coach, client: Client) -> None:
    """Assign ``coach`` to ``client`` preserving other coach types."""
    coach_clients = coach.assigned_to or []
    if client.profile not in coach_clients:
        coach_clients.append(client.profile)
        await APIService.profile.update_coach_profile(coach.id, {"assigned_to": coach_clients})
        await Cache.coach.update_coach(coach.profile, {"assigned_to": coach_clients})

    assigned = list(client.assigned_to or [])

    for coach_id in list(assigned):
        try:
            existing = await Cache.coach.get_coach(coach_id)
        except CoachNotFoundError:
            continue
        if existing.coach_type == coach.coach_type:
            assigned.remove(coach_id)
            break

    if coach.profile not in assigned:
        assigned.append(coach.profile)

    await APIService.profile.update_client_profile(client.id, {"assigned_to": assigned})
    await Cache.client.update_client(client.profile, {"assigned_to": assigned})


async def get_assigned_coach(client: Client, *, coach_type: CoachType | None = None) -> Coach | None:
    """Return client's coach filtered by ``coach_type`` if provided."""
    if not client.assigned_to:
        return None
    for cid in client.assigned_to:
        try:
            coach = await Cache.coach.get_coach(cid)
        except CoachNotFoundError:
            continue
        if coach_type is None or coach.coach_type == coach_type:
            return coach
    return None


async def get_assigned_coach_id(client: Client, *, coach_type: CoachType | None = None) -> int | None:
    coach = await get_assigned_coach(client, coach_type=coach_type)
    return coach.profile if coach else None


async def check_assigned_clients(profile_id: int) -> bool:
    try:
        coach = await Cache.coach.get_coach(profile_id)
    except CoachNotFoundError:
        logger.info(f"Coach not found for profile_id {profile_id} in check_assigned_clients.")
        return False

    assigned_clients = coach.assigned_to or []

    for client in assigned_clients:
        try:
            subscription = await Cache.workout.get_latest_subscription(client)
            if subscription.enabled:
                return True
        except SubscriptionNotFoundError:
            pass

        if await Cache.payment.get_status(client, "program"):
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

    if profile.role == "coach":
        try:
            return await Cache.coach.get_coach(profile.id)
        except CoachNotFoundError:
            logger.error(
                f"CoachNotFoundError for an existing profile {profile.id}. This might indicate data inconsistency."
            )
            raise ValueError(f"Coach data not found for existing profile id {profile.id}")

    raise ValueError(f"Unknown profile role: {profile.role}")


async def answer_profile(
    cbq: TgCallbackQuery,
    profile: Profile,
    user: Coach | Client,
    text: str,
    *,
    show_balance: bool = False,
) -> None:
    from bot.keyboards import profile_menu_kb

    message = cbq.message  # Optional[TgMessage]
    if message is None:
        return

    avatar_manager = get_avatar_manager()

    if profile.role == "coach" and isinstance(user, Coach):
        if user.coach_type == CoachType.ai_coach or not user.profile_photo:
            file_path = _IMAGES_DIR / "ai_coach.png"
            if file_path.exists():
                avatar = FSInputFile(file_path)
                try:
                    await message.answer_photo(
                        avatar,
                        caption=text,
                        reply_markup=profile_menu_kb(profile.language, show_balance=show_balance),
                    )
                    return
                except TelegramBadRequest:
                    logger.warning("Photo not found for AI coach")
        else:
            photo_url = f"https://storage.googleapis.com/{avatar_manager.bucket_name}/{user.profile_photo}"
            try:
                await message.answer_photo(
                    photo_url,
                    caption=text,
                    reply_markup=profile_menu_kb(profile.language, show_balance=show_balance),
                )
                return
            except TelegramBadRequest:
                logger.warning(f"Photo not found for coach {profile.id}")

    if profile.role == "client" and isinstance(user, Client):
        if user.profile_photo:
            photo_url = f"https://storage.googleapis.com/{avatar_manager.bucket_name}/{user.profile_photo}"
            try:
                await message.answer_photo(
                    photo_url,
                    caption=text,
                    reply_markup=profile_menu_kb(profile.language, show_balance=show_balance),
                )
                return
            except TelegramBadRequest:
                logger.warning(f"Photo not found for client {profile.id}")

        avatar_name = "female.png" if getattr(user, "gender", None) == "female" else "male.png"
        file_path = _IMAGES_DIR / avatar_name

        if file_path.exists():
            avatar_file = FSInputFile(file_path)
            try:
                await message.answer_photo(
                    avatar_file,
                    caption=text,
                    reply_markup=profile_menu_kb(profile.language, show_balance=show_balance),
                )
                return
            except TelegramBadRequest as e:
                logger.warning(f"Failed to send default avatar for client {profile.id}: {e}")
        else:
            logger.error(f"Default avatar file not found: {file_path}")

    await message.answer(text, reply_markup=profile_menu_kb(profile.language, show_balance=show_balance))


async def get_clients_to_survey() -> list[Profile]:
    clients_with_workout: list[Profile] = []

    try:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%A").lower()
        raw_clients = await Cache.client.get_all("clients") or []

        for profile_id_str in raw_clients:
            try:
                profile_id = int(profile_id_str)
                client = await Cache.client.get_client(profile_id)
                subscription = await Cache.workout.get_latest_subscription(client.id)
                if not subscription:
                    continue

                if not isinstance(subscription.workout_days, list):
                    logger.warning(f"Invalid workout_days format for client_id={profile_id}")
                    continue

                if (
                    subscription.enabled
                    and subscription.exercises
                    and yesterday in [day.lower() for day in subscription.workout_days]
                ):
                    profile = await APIService.profile.get_profile(client.profile)
                    if profile is not None:
                        clients_with_workout.append(profile)

            except Exception as client_err:
                logger.warning(f"Skipping client_id={profile_id_str} due to error: {client_err}")
                continue

    except Exception as e:
        logger.error(f"Failed to load clients for survey: {e}")

    return clients_with_workout


async def _get_client_and_coach(profile_id: int) -> tuple[Client, Coach]:
    client = await Cache.client.get_client(profile_id)
    if not client.assigned_to:
        raise ClientNotAssignedError
    coach = await get_assigned_coach(client, coach_type=CoachType.human)
    if coach is None:
        raise CoachNotFoundError
    return client, coach
