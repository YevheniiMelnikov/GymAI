from datetime import datetime
from typing import cast

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.utils.other import del_msg
from bot.keyboards import select_service_kb, workout_type_kb
from bot.states import States

from core.cache import Cache
from core.services import APIService
from bot.utils.menus import show_main_menu
from bot.utils.workout_plans import cache_program_data
from bot.texts import msg_text, btn_text
from core.models import Profile

payment_router = Router()


@payment_router.callback_query(States.gift)
async def get_the_gift(callback_query: CallbackQuery, state: FSMContext):
    if callback_query.data != "get":
        return

    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    await callback_query.answer(btn_text("done", profile.language))
    await Cache.client.update_client(profile.id, dict(status="waiting_for_text"))
    message = callback_query.message
    assert message
    await message.answer(msg_text("workout_type", profile.language), reply_markup=workout_type_kb(profile.language))
    await state.update_data(new_client=True)
    await state.set_state(States.workout_type)
    await del_msg(cast(Message | CallbackQuery | None, callback_query))


@payment_router.callback_query(States.payment_choice)
async def payment_choice(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    if callback_query.data == "back":
        await state.set_state(States.select_service)
        message = callback_query.message
        assert message
        await message.answer(
            msg_text("select_service", profile.language),
            reply_markup=select_service_kb(profile.language),
        )
        await del_msg(cast(Message | CallbackQuery | None, callback_query))
        return

    if not callback_query.data:
        await callback_query.answer("Invalid option", show_alert=True)
        return

    parts = callback_query.data.split("_")
    if len(parts) < 2:
        await callback_query.answer("Invalid option", show_alert=True)
        return
    option = parts[1]

    client = await Cache.client.get_client(profile.id)
    if not client or not client.assigned_to:
        await callback_query.answer("Client or coach not found", show_alert=True)
        return
    coach_id = client.assigned_to.pop()
    coach = await Cache.coach.get_coach(coach_id)
    if not coach:
        await callback_query.answer("Coach not found", show_alert=True)
        return

    await state.update_data(request_type=option, client=client.model_dump(), coach=coach.model_dump())
    message = callback_query.message
    assert message
    await message.answer(msg_text("workout_type", profile.language), reply_markup=workout_type_kb(profile.language))
    await state.set_state(States.workout_type)
    await del_msg(cast(Message | CallbackQuery | None, callback_query))


@payment_router.callback_query(States.handle_payment)
async def handle_payment(callback_query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    if callback_query.data == "done":
        order_id = data.get("order_id")
        amount = data.get("amount")
        request_type = data.get("request_type")
        wishes = data.get("wishes")
        workout_type = data.get("workout_type")
        workout_days = data.get("workout_days", [])

        if not isinstance(order_id, str) or not isinstance(amount, int) or not isinstance(request_type, str):
            await callback_query.answer("Invalid payment data", show_alert=True)
            return

        if request_type == "program":
            await cache_program_data(data, profile.id)
        else:
            client = await Cache.client.get_client(profile.id)
            if not client or not client.assigned_to:
                await callback_query.answer("Client or coach not found", show_alert=True)
                return
            coach_id = client.assigned_to.pop()
            coach = await Cache.coach.get_coach(coach_id)
            if not coach:
                await callback_query.answer("Coach not found", show_alert=True)
                return

            if not isinstance(wishes, str):
                wishes = ""

            subscription_id = await APIService.workout.create_subscription(
                profile.id, workout_days, wishes, coach.subscription_price
            )

            subscription_data = {
                "id": subscription_id,
                "payment_date": datetime.today().strftime("%Y-%m-%d"),
                "enabled": False,
                "price": coach.subscription_price,
                "client_profile": profile.id,
                "workout_days": workout_days,
                "workout_type": workout_type,
                "wishes": wishes,
            }
            await Cache.workout.update_program(profile.id, subscription_data)

        await Cache.workout.set_payment_status(profile.id, True, request_type)
        await APIService.payment.create_payment(profile.id, request_type, order_id, amount)
        await callback_query.answer(msg_text("payment_in_progress", profile.language), show_alert=True)

    message = callback_query.message
    if message and isinstance(message, Message):
        await show_main_menu(message, profile, state)
    await del_msg(cast(Message | CallbackQuery | None, callback_query))
