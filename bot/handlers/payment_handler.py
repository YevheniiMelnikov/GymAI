from contextlib import suppress
from datetime import datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.keyboards import select_service_kb, workout_type_kb
from bot.states import States

from core.cache import Cache
from core.services import APIService
from functions.menus import show_main_menu
from functions.workout_plans import cache_program_data
from bot.texts.text_manager import msg_text, btn_text
from core.models import Profile

payment_router = Router()


@payment_router.callback_query(States.gift, F.data == "get")
async def get_the_gift(callback_query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    await callback_query.answer(btn_text("done", profile.language))
    await Cache.client.update_client(profile.id, dict(status="waiting_for_text"))
    await callback_query.message.answer(
        msg_text("workout_type", profile.language), reply_markup=workout_type_kb(profile.language)
    )
    await state.update_data(new_client=True)
    await state.set_state(States.workout_type)
    await callback_query.message.delete()


@payment_router.callback_query(States.payment_choice)
async def payment_choice(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    if callback_query.data == "back":
        await state.set_state(States.select_service)
        await callback_query.message.answer(
            msg_text("select_service", profile.language),
            reply_markup=select_service_kb(profile.language),
        )
        await callback_query.message.delete()
        return

    option = callback_query.data.split("_")[1]
    client = await Cache.client.get_client(profile.id)
    coach_id = client.assigned_to.pop()
    coach = await Cache.coach.get_coach(coach_id)
    await state.update_data(request_type=option, client=client.model_dump(), coach=coach.model_dump())
    await callback_query.message.answer(
        msg_text("workout_type", profile.language), reply_markup=workout_type_kb(profile.language)
    )
    await state.set_state(States.workout_type)
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


@payment_router.callback_query(States.handle_payment)
async def handle_payment(callback_query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    if callback_query.data == "done":
        order_id = data.get("order_id")
        amount = data.get("amount")
        if data.get("request_type") == "program":
            await cache_program_data(data, profile.id)
        else:
            days = data.get("workout_days", [])
            client = await Cache.client.get_client(profile.id)
            coach = await Cache.coach.get_coach(client.assigned_to.pop())
            subscription_id = await APIService.workout.create_subscription(
                profile.id, days, data.get("wishes"), coach.subscription_price
            )

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
            await Cache.workout.update_program(profile.id, subscription_data)
        await Cache.workout.set_payment_status(profile.id, True, data.get("request_type"))
        await APIService.payment.create_payment(profile.id, data.get("request_type"), order_id, amount)
        await callback_query.answer(msg_text("payment_in_progress", profile.language), show_alert=True)

    await show_main_menu(callback_query.message, profile, state)
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()
