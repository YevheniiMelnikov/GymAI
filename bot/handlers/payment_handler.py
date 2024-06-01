import datetime
from contextlib import suppress

import loguru
from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards import choose_payment_options, select_program_type
from bot.states import States
from common.functions import show_main_menu
from common.user_service import user_service
from texts.text_manager import MessageText, translate

payment_router = Router()
logger = loguru.logger


@payment_router.callback_query(States.select_program_type)
async def program_type(callback_query: CallbackQuery, state: FSMContext):
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    if callback_query.data == "subscription":
        subscription_img = f"https://storage.googleapis.com/bot_payment_options/subscription_{profile.language}.jpeg"
        await callback_query.message.answer_photo(
            photo=subscription_img,
            reply_markup=choose_payment_options(profile.language, "subscription"),
        )
        await state.set_state(States.payment_choice)
    elif callback_query.data == "program":
        program_img = f"https://storage.googleapis.com/bot_payment_options/program_{profile.language}.jpeg"
        await callback_query.message.answer_photo(
            photo=program_img,
            reply_markup=choose_payment_options(profile.language, "program"),
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
        return

    action = callback_query.data.split("_")[1]

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💰", callback_data=action)]])  # payment mock
    await callback_query.message.answer("click to pay 👇", reply_markup=kb)
    await state.set_state(States.handle_payment)

    # link = payment_service.program_link() if action == "program" else payment_service.subscription()
    # await callback_query.message.answer(translate(MessageText.payment_link, profile.language).format(link=link))


@payment_router.callback_query(States.handle_payment)  # payment mock
async def handle_payment(callback_query: CallbackQuery, state: FSMContext):
    # TODO: HANDLE PAYMENT FAILURE
    await callback_query.answer("✅")
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    if callback_query.data == "subscription":
        subscription_data = {"created_at": datetime.date.today().isoformat()}
        user_service.storage.save_subscription(profile.id, subscription_data)
    else:
        user_service.storage.set_program_payment_status(profile.id, True)

    # TODO: ALSO UPDATE POSTGRES DATA
    await callback_query.message.answer(translate(MessageText.payment_success, profile.language))
    await state.set_state(States.main_menu)
    await show_main_menu(callback_query.message, profile, state)
