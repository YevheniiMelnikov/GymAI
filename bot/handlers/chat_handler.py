from typing import cast

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.utils.ask_ai import start_ask_ai_prompt
from core.schemas import Profile
from bot.utils.menus import show_main_menu
from bot.utils.bot import del_msg

chat_router = Router()


@chat_router.callback_query(F.data.in_({"quit", "later"}))
async def close_notification(callback_query: CallbackQuery, state: FSMContext) -> None:
    if callback_query.message and isinstance(callback_query.message, Message):
        await del_msg(callback_query.message)
    data = await state.get_data()
    profile_dict = data.get("profile")
    if profile_dict:
        profile = Profile.model_validate(profile_dict)
        if callback_query.message and isinstance(callback_query.message, Message):
            await show_main_menu(cast(Message, callback_query.message), profile, state)


@chat_router.callback_query(F.data.startswith("answer"))
async def answer_message(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    assert profile is not None

    data_str = cast(str, callback_query.data)
    try:
        int(data_str.split("_", 1)[1])
    except (IndexError, ValueError):
        await callback_query.answer("Invalid recipient id")
        return


@chat_router.callback_query(F.data.startswith("ask_ai_again"))
async def ask_ai_repeat(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        await callback_query.answer()
        return
    profile = Profile.model_validate(profile_data)
    handled = await start_ask_ai_prompt(
        callback_query,
        profile,
        state,
        delete_origin=False,
        show_balance_menu_on_insufficient=False,
    )
    if handled:
        await callback_query.answer()


@chat_router.callback_query(F.data == "ask_ai_main_menu")
async def ask_ai_main_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        await callback_query.answer()
        return
    profile = Profile.model_validate(profile_data)
    message = callback_query.message
    if message is None or not isinstance(message, Message):
        await callback_query.answer()
        return
    await callback_query.answer()
    await show_main_menu(message, profile, state, delete_source=False)
