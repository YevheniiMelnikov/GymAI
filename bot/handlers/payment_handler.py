from contextlib import suppress

import loguru
from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.keyboards import choose_payment_options, select_program_type
from bot.states import States
from common.file_manager import payment_img_manager
from common.functions import show_main_menu
from common.user_service import user_service
from texts.text_manager import MessageText, translate

payment_router = Router()
logger = loguru.logger


@payment_router.callback_query(States.select_program_type)
async def program_type(callback_query: CallbackQuery, state: FSMContext):
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    if callback_query.data == "subscription":
        subscription_img = payment_img_manager.generate_signed_url(f"subscription_{profile.language}.jpg")
        await callback_query.message.answer_photo(
            photo=subscription_img,
            reply_markup=choose_payment_options(profile.language),
        )
        await state.set_state(States.payment_choice)
    elif callback_query.data == "program":
        program_img = payment_img_manager.generate_signed_url(f"program_{profile.language}.jpg")
        await callback_query.message.answer_photo(
            photo=program_img,
            reply_markup=choose_payment_options(profile.language),
        )
        await state.set_state(States.payment_choice)
    else:
        await state.set_state(States.main_menu)
        await show_main_menu(callback_query.message, profile, state)

    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


@payment_router.callback_query(States.payment_choice)
async def payment_choice(callback_query: CallbackQuery, state: FSMContext):
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    if callback_query.data == "back":
        await state.set_state(States.select_program_type)
        await callback_query.message.answer(
            text=translate(MessageText.no_program, lang=profile.language),
            reply_markup=select_program_type(profile.language),
        )
        await callback_query.message.delete()
    else:
        await callback_query.answer("will be added soon")
