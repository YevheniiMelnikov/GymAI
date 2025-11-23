from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

from loguru import logger

from bot.texts import MessageText, msg_text
from bot.utils.bot import answer_msg, del_msg, delete_messages
from config.app_settings import settings
from core.cache import Cache
from core.exceptions import ProfileNotFoundError
from core.schemas import Profile
from core.services import get_avatar_manager
from core.services.internal import APIService

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.fsm.context import FSMContext
    from aiogram.types import Message as TgMessage, CallbackQuery as TgCallbackQuery

_IMAGES_DIR = Path(__file__).resolve().parent.parent / "images"


async def update_profile_data(
    message: "TgMessage",
    state: "FSMContext",
    bot: "Bot",
) -> None:
    data = await state.get_data()
    await delete_messages(state)

    try:
        profile = await Cache.profile.get_profile(message.chat.id)
        assert profile is not None

        user_data = {**data}
        user_data.pop("profile", None)

        credits_delta = data.pop("credits_delta", 0)
        if credits_delta and (profile.credits or 0) < settings.PACKAGE_START_CREDITS:
            remaining = settings.PACKAGE_START_CREDITS - (profile.credits or 0)
            credits_delta_to_apply = min(credits_delta, remaining)
            user_data["credits"] = (profile.credits or 0) + credits_delta_to_apply
        await Cache.profile.update_profile(message.chat.id, user_data)
        await APIService.profile.update_profile(profile.id, user_data)
        await Cache.profile.update_record(profile.id, user_data)

        await answer_msg(message, msg_text(MessageText.your_data_updated, data.get("lang", settings.DEFAULT_LANG)))

        from bot.utils.menus import show_main_menu

        await show_main_menu(message, profile, state)

    except Exception as e:
        logger.error(f"Unexpected error updating profile: {e}")
        await answer_msg(message, msg_text(MessageText.unexpected_error, data.get("lang", settings.DEFAULT_LANG)))

    finally:
        await del_msg(cast("TgMessage | TgCallbackQuery | None", message))


async def fetch_user(profile: Profile) -> Profile:
    try:
        return await Cache.profile.get_record(profile.id)
    except ProfileNotFoundError:
        logger.error(
            f"ProfileNotFoundError for an existing profile {profile.id}. This might indicate data inconsistency."
        )
        raise ValueError(f"Profile data not found for existing profile id {profile.id}")


async def answer_profile(
    cbq: "TgCallbackQuery",
    profile: Profile,
    user: Profile,
    text: str,
    *,
    show_balance: bool = False,
) -> None:
    from bot.keyboards import profile_menu_kb

    message = cbq.message
    if message is None:
        return

    avatar_manager = get_avatar_manager()
    avatar_name = "female.png" if getattr(user, "gender", None) == "female" else "male.png"
    file_path = _IMAGES_DIR / avatar_name
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
            logger.warning(f"Photo not found for profile {profile.id}")

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
            logger.warning(f"Failed to send default avatar for profile {profile.id}: {e}")
    else:
        logger.error(f"Default avatar file not found: {file_path}")

    await message.answer(text, reply_markup=profile_menu_kb(profile.language, show_balance=show_balance))


async def get_profiles_to_survey() -> list[Profile]:
    profiles_with_workout: list[Profile] = []

    try:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%A").lower()
        raw_profiles = await Cache.profile.get_all_records() or {}

        for profile_id_str in raw_profiles:
            try:
                profile_id = int(profile_id_str)
                cached_profile = await Cache.profile.get_record(profile_id)
                subscription = await Cache.workout.get_latest_subscription(cached_profile.id)
                if not subscription:
                    continue

                if not isinstance(subscription.workout_days, list):
                    logger.warning(f"Invalid workout_days format for profile_id={profile_id}")
                    continue

                if (
                    subscription.enabled
                    and subscription.exercises
                    and yesterday in [day.lower() for day in subscription.workout_days]
                ):
                    profile = await APIService.profile.get_profile(cached_profile.id)
                    if profile is not None:
                        profiles_with_workout.append(profile)

            except Exception as profile_err:
                logger.warning(f"Skipping profile_id={profile_id_str} due to error: {profile_err}")
                continue

    except Exception as e:
        logger.error(f"Failed to load profiles for survey: {e}")

    return profiles_with_workout
