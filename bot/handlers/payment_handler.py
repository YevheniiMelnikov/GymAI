from contextlib import suppress

import loguru
from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.keyboards import select_service, workout_type
from bot.states import States
from common.functions import client_request, show_main_menu
from common.models import Client, Coach
from common.payment_service import payment_service
from common.user_service import user_service
from texts.text_manager import MessageText, translate

payment_router = Router()
logger = loguru.logger


@payment_router.callback_query(States.payment_choice)
async def payment_choice(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    if callback_query.data == "back":
        await state.set_state(States.select_service)
        await callback_query.message.answer(
            text=translate(MessageText.select_service, lang=profile.language),
            reply_markup=select_service(profile.language),
        )
        await callback_query.message.delete()
        return

    option = callback_query.data.split("_")[1]
    client = user_service.storage.get_client_by_id(profile.id)
    coach_id = client.assigned_to[0]
    coach = user_service.storage.get_coach_by_id(coach_id)
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
    data = await state.get_data()
    coach = Coach.from_dict(data.get("coach"))
    client = Client.from_dict(data.get("client"))
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    if callback_query.data == "subscription":
        payment_success = await payment_service.process_subscription_payment(state, profile)
    else:
        payment_success = await payment_service.process_program_payment(state, profile)
    if payment_success:
        await callback_query.message.answer(translate(MessageText.payment_success, profile.language))
        await client_request(coach, client, state)
        await state.set_state(States.main_menu)
        await show_main_menu(callback_query.message, profile, state)
    else:
        await callback_query.message.answer(translate(MessageText.payment_failure, profile.language))
        # TODO: HANDLE PAYMENT FAILURE
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()
