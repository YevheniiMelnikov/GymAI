from contextlib import suppress
from datetime import datetime

import loguru
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from rest_framework.exceptions import ValidationError

from bot.keyboards import select_service, workout_type
from bot.states import States
from common.cache_manager import cache_manager
from functions.menus import show_main_menu
from functions.profiles import get_or_load_profile
from functions.workout_plans import cache_program_data
from common.models import Client, Coach
from services.payment_service import payment_service
from services.user_service import user_service
from services.workout_service import workout_service
from bot.texts.resources import ButtonText, MessageText
from bot.texts.text_manager import translate

payment_router = Router()
logger = loguru.logger


@payment_router.callback_query(States.gift, F.data == "get")
async def get_the_gift(callback_query: CallbackQuery, state: FSMContext):
    profile = await get_or_load_profile(callback_query.from_user.id)
    await callback_query.answer(translate(ButtonText.done, profile.language))
    cache_manager.set_client_data(profile.id, {"status": "waiting_for_text"})
    await callback_query.message.answer(
        translate(MessageText.workout_type), reply_markup=workout_type(profile.language)
    )
    await state.update_data(new_client=True)
    await state.set_state(States.workout_type)
    await callback_query.message.delete()


@payment_router.callback_query(States.payment_choice)
async def payment_choice(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    profile = await get_or_load_profile(callback_query.from_user.id)
    if callback_query.data == "back":
        await state.set_state(States.select_service)
        await callback_query.message.answer(
            text=translate(MessageText.select_service, lang=profile.language),
            reply_markup=select_service(profile.language),
        )
        await callback_query.message.delete()
        return

    option = callback_query.data.split("_")[1]
    client = cache_manager.get_client_by_id(profile.id)
    coach_id = client.assigned_to.pop()
    coach = cache_manager.get_coach_by_id(coach_id)
    await state.update_data(request_type=option, client=Client.to_dict(client), coach=Coach.to_dict(coach))
    await callback_query.message.answer(
        translate(MessageText.workout_type), reply_markup=workout_type(profile.language)
    )
    await state.set_state(States.workout_type)
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


@payment_router.callback_query(States.handle_payment)
async def handle_payment(callback_query: CallbackQuery, state: FSMContext):
    profile = await get_or_load_profile(callback_query.from_user.id)
    if callback_query.data == "done":
        data = await state.get_data()
        order_id = data.get("order_id")
        amount = data.get("amount")
        if data.get("request_type") == "program":
            cache_program_data(data, profile.id)
        else:
            days = data.get("workout_days", [])
            client = cache_manager.get_client_by_id(profile.id)
            coach = cache_manager.get_coach_by_id(client.assigned_to.pop())
            auth_token = await user_service.get_user_token(profile.id)
            try:
                subscription_id = await workout_service.create_subscription(
                    profile.id, days, data.get("wishes"), coach.subscription_price, auth_token
                )
            except ValidationError as e:
                logger.error(f"Failed to create subscription: {e}")
                await callback_query.answer(translate(MessageText.unexpected_error, profile.language), show_alert=True)
                return

            subscription_data = {
                "id": subscription_id,
                "payment_date": datetime.today().strftime("%Y-%m-%d"),
                "enabled": False,
                "price": coach.subscription_price,
                "client_profile": profile.id,
                "workout_days": days,
                "workout_type": data.get("workout_type"),
                "wishes": data.get("wishes"),
            }
            cache_manager.save_subscription(profile.id, subscription_data)
        cache_manager.set_payment_status(profile.id, True, data.get("request_type"))
        await payment_service.create_payment(profile.id, data.get("request_type"), order_id, amount)
        await callback_query.answer(translate(MessageText.payment_in_progress, profile.language), show_alert=True)

    await show_main_menu(callback_query.message, profile, state)
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()
