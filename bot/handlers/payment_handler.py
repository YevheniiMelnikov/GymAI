from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.states import States
from common.file_manager import file_manager
from common.functions import show_main_menu
from common.user_service import user_service

payment_router = Router()


@payment_router.callback_query(States.select_program_type)  # TODO: IMPLEMENT
async def program_type(callback: CallbackQuery, state: FSMContext):
    profile = user_service.storage.get_current_profile(callback.from_user.id)
    if callback.data == "subscription":
        await file_manager.generate_signed_url()
        await callback.answer("subscription will be added soon")
    elif callback.data == "program":
        await callback.answer("program will be added soon")
    else:
        await state.set_state(States.main_menu)
        await show_main_menu(callback.message, profile, state)
