from contextlib import suppress
from datetime import datetime

from loguru import logger
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from rest_framework.exceptions import ValidationError

from bot.keyboards import select_service_kb, workout_type_kb
from bot.states import States
from core.cache_manager import CacheManager
from functions.menus import show_main_menu
from functions.profiles import get_user_profile
from functions.workout_plans import cache_program_data
from core.models import Client, Coach
from core.services.payment_service import PaymentService
from core.services import WorkoutService
from bot.texts.text_manager import msg_text, btn_text

payment_router = Router()


@payment_router.callback_query(States.gift, F.data == "get")
async def get_the_gift(callback_query: CallbackQuery, state: FSMContext):
    profile = await get_user_profile(callback_query.from_user.id)
    await callback_query.answer(btn_text("done", profile.language))
    CacheManager.set_client_data(profile.id, {"status": "waiting_for_text"})
    await callback_query.message.answer(
        msg_text("workout_type", profile.language), reply_markup=workout_type_kb(profile.language)
    )
    await state.update_data(new_client=True)
    await state.set_state(States.workout_type)
    await callback_query.message.delete()


@payment_router.callback_query(States.payment_choice)
async def payment_choice(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    profile = await get_user_profile(callback_query.from_user.id)
    if callback_query.data == "back":
        await state.set_state(States.select_service)
        await callback_query.message.answer(
            msg_text("select_service", profile.language),
            reply_markup=select_service_kb(profile.language),
        )
        await callback_query.message.delete()
        return

    option = callback_query.data.split("_")[1]
    client = CacheManager.get_client_by_id(profile.id)
    coach_id = client.assigned_to.pop()
    coach = CacheManager.get_coach_by_id(coach_id)
    await state.update_data(request_type=option, client=Client.to_dict(client), coach=Coach.to_dict(coach))
    await callback_query.message.answer(
        msg_text("workout_type", profile.language), reply_markup=workout_type_kb(profile.language)
    )
    await state.set_state(States.workout_type)
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


@payment_router.callback_query(States.handle_payment)
async def handle_payment(callback_query: CallbackQuery, state: FSMContext):
    profile = await get_user_profile(callback_query.from_user.id)
    if callback_query.data == "done":
        data = await state.get_data()
        order_id = data.get("order_id")
        amount = data.get("amount")
        if data.get("request_type") == "program":
            cache_program_data(data, profile.id)
        else:
            days = data.get("workout_days", [])
            client = CacheManager.get_client_by_id(profile.id)
            coach = CacheManager.get_coach_by_id(client.assigned_to.pop())
            try:
                subscription_id = await WorkoutService.create_subscription(
                    profile.id, days, data.get("wishes"), coach.subscription_price
                )
            except ValidationError as e:
                logger.error(f"Failed to create subscription: {e}")
                await callback_query.answer(msg_text("unexpected_error", profile.language), show_alert=True)
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
            CacheManager.save_subscription(profile.id, subscription_data)
        CacheManager.set_payment_status(profile.id, True, data.get("request_type"))
        await PaymentService.create_payment(profile.id, data.get("request_type"), order_id, amount)
        await callback_query.answer(msg_text("payment_in_progress", profile.language), show_alert=True)

    await show_main_menu(callback_query.message, profile, state)
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()
