from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from typing import cast
from loguru import logger

from bot.texts import msg_text
from bot.utils.chat import send_message
from bot.utils.other import del_msg
from config.env_settings import settings
from core.cache import Cache
from core.exceptions import CoachNotFoundError
from core.services import APIService

admin_router = Router()


@admin_router.callback_query()
async def approve_coach(callback_query: CallbackQuery, state: FSMContext) -> None:
    if not callback_query.data or not callback_query.data.startswith("approve"):
        return

    data_str = cast(str, callback_query.data)
    try:
        profile_id = int(data_str.split("_", 1)[1])
    except (IndexError, ValueError):
        await callback_query.answer("Invalid profile id")
        return

    try:
        coach = await Cache.coach.get_coach(profile_id)
    except CoachNotFoundError:
        await callback_query.answer(f"Coach not found for profile {profile_id}")
        return

    await APIService.profile.update_coach_profile(coach.id, {"verified": True})
    await Cache.coach.update_coach(coach.id, {"verified": True})
    await callback_query.answer("👍")
    coach = await Cache.coach.get_coach(profile_id)
    coach_profile = await Cache.profile.get_profile(profile_id)
    lang = coach_profile.language or settings.DEFAULT_LANG
    if coach:
        await send_message(coach, msg_text("coach_verified", lang), state, include_incoming_message=False)
    if callback_query.message and isinstance(callback_query.message, Message):
        await del_msg(callback_query.message)
    logger.info(f"Coach verification for profile_id {profile_id} approved")


@admin_router.callback_query()
async def decline_coach(callback_query: CallbackQuery, state: FSMContext) -> None:
    if not callback_query.data or not callback_query.data.startswith("decline"):
        return

    data_str = cast(str, callback_query.data)
    try:
        profile_id = int(data_str.split("_", 1)[1])
    except (IndexError, ValueError):
        await callback_query.answer("Invalid profile id")
        return

    await callback_query.answer("👎")
    coach = await Cache.coach.get_coach(profile_id)
    coach_profile = await Cache.profile.get_profile(profile_id)
    lang = coach_profile.language or settings.DEFAULT_LANG
    if coach:
        await send_message(coach, msg_text("coach_declined", lang), state, include_incoming_message=False)
    if callback_query.message and isinstance(callback_query.message, Message):
        await del_msg(callback_query.message)
    logger.info(f"Coach verification for profile_id {profile_id} declined")
