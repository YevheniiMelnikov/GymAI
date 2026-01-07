from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.states import States
from core.schemas import Profile
from bot.utils.ask_ai import start_ask_ai_prompt
from bot.utils.menus import show_my_profile_menu

menu_router = Router()


@menu_router.callback_query(F.data == "quit")
async def dismiss_message(callback_query: CallbackQuery) -> None:
    if callback_query.message:
        await callback_query.message.delete()
    await callback_query.answer()


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

    elif cb_data == "my_profile":
        await show_my_profile_menu(callback_query, profile, state)
