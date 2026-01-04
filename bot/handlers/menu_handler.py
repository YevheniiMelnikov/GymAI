from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from bot.states import States
from core.cache import Cache
from core.schemas import Profile
from bot.utils.ask_ai import start_ask_ai_prompt
from bot.utils.menus import show_main_menu, show_my_profile_menu, start_diet_flow
from core.services import APIService

menu_router = Router()


@menu_router.callback_query(F.data == "main_menu")
async def main_menu_shortcut(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    profile: Profile | None = None
    if profile_data:
        profile = Profile.model_validate(profile_data)
    else:
        try:
            profile = await Cache.profile.get_profile(callback_query.from_user.id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"main_menu_shortcut_profile_missing tg_id={callback_query.from_user.id} err={exc!s}")
            profile = None
        if profile is None:
            profile = await APIService.profile.get_profile_by_tg_id(callback_query.from_user.id)
            if profile is not None:
                await Cache.profile.save_record(profile.id, profile.model_dump(mode="json"))
    if profile is None:
        await callback_query.answer()
        return
    message = callback_query.message
    if message is None or not isinstance(message, Message):
        await callback_query.answer()
        return
    await callback_query.answer()
    await show_main_menu(message, profile, state)


@menu_router.callback_query(States.main_menu)
async def main_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    message = callback_query.message
    if message is None or not isinstance(message, Message):
        return
    cb_data = callback_query.data or ""

    if cb_data == "back":
        await show_my_profile_menu(callback_query, profile, state)
        return

    if cb_data == "ask_ai":
        await start_ask_ai_prompt(
            callback_query,
            profile,
            state,
            delete_origin=True,
            show_balance_menu_on_insufficient=True,
        )
        return

    elif cb_data == "create_diet":
        await start_diet_flow(callback_query, profile, state, delete_origin=True)
        return

    elif cb_data == "my_profile":
        await show_my_profile_menu(callback_query, profile, state)
