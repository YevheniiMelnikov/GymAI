from contextlib import suppress

import loguru
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.keyboards import select_service, workout_type
from bot.states import States
from common.backend_service import backend_service
from common.functions.chat import client_request
from common.functions.menus import show_main_menu
from common.models import Client, Coach
from common.payment_service import payment_service
from texts.text_manager import ButtonText, MessageText, translate

payment_router = Router()
logger = loguru.logger


@payment_router.callback_query(States.gift, F.data == "get")
async def get_the_gift(callback_query: CallbackQuery, state: FSMContext):
    profile = backend_service.cache.get_current_profile(callback_query.from_user.id)
    await callback_query.answer(translate(ButtonText.done, profile.language))
    await callback_query.message.answer(
        translate(MessageText.workout_type), reply_markup=workout_type(profile.language)
    )
    await state.update_data(new_client=True)
    await state.set_state(States.workout_type)
    await callback_query.message.delete()


@payment_router.callback_query(States.payment_choice)
async def payment_choice(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    profile = backend_service.cache.get_current_profile(callback_query.from_user.id)
    if callback_query.data == "back":
        await state.set_state(States.select_service)
        await callback_query.message.answer(
            text=translate(MessageText.select_service, lang=profile.language),
            reply_markup=select_service(profile.language),
        )
        await callback_query.message.delete()
        return

    option = callback_query.data.split("_")[1]
    client = backend_service.cache.get_client_by_id(profile.id)
    coach_id = client.assigned_to.pop()
    coach = backend_service.cache.get_coach_by_id(coach_id)
    await state.update_data(request_type=option, client=Client.to_dict(client), coach=Coach.to_dict(coach))
    await callback_query.message.answer(
        translate(MessageText.workout_type), reply_markup=workout_type(profile.language)
    )
    await state.set_state(States.workout_type)
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


@payment_router.callback_query(States.handle_payment)
async def handle_payment(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    profile = backend_service.cache.get_current_profile(callback_query.from_user.id)
    data = await state.get_data()
    order_number = data.get("order_number")
    amount = data.get("amount")
    await backend_service.create_payment(profile.id, callback_query.from_user.id, order_number, amount)
    if await payment_service.process_webhook(data, profile):
        await callback_query.message.answer(translate(MessageText.payment_success, profile.language))
        coach = Coach.from_dict(data.get("coach"))
        client = Client.from_dict(data.get("client"))
        await client_request(coach, client, state)
    else:
        await callback_query.message.answer(translate(MessageText.payment_failure, profile.language))
    await show_main_menu(callback_query.message, profile, state)
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()
