from datetime import datetime
from decimal import InvalidOperation, Decimal, ROUND_HALF_UP
from typing import cast

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from loguru import logger

from bot.utils.bot import del_msg, answer_msg
from bot.keyboards import select_service_kb, workout_type_kb
from bot.states import States

from core.cache import Cache
from core.cache.payment import PaymentCacheManager
from core.enums import ProfileStatus, PaymentStatus, SubscriptionPeriod
from core.services import APIService
from bot.utils.menus import show_main_menu, show_my_workouts_menu, show_balance_menu
from core.schemas import Profile
from bot.utils.workout_plans import cache_program_data, process_new_subscription
from bot.texts import msg_text, btn_text
from core.exceptions import ProfileNotFoundError

payment_router = Router()


@payment_router.callback_query(States.gift)
async def get_the_gift(callback_query: CallbackQuery, state: FSMContext) -> None:
    if callback_query.data != "get":
        return

    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    await callback_query.answer(btn_text("done", profile.language))
    profile_record = await Cache.profile.get_record(profile.id)
    await Cache.profile.update_record(profile_record.id, dict(status=ProfileStatus.waiting_for_text))
    await answer_msg(
        msg_obj=callback_query,
        text=msg_text("workout_type", profile.language),
        reply_markup=workout_type_kb(profile.language),
    )
    await state.update_data(new_profile=True)
    await state.set_state(States.workout_type)
    await del_msg(cast(Message | CallbackQuery | None, callback_query))


@payment_router.callback_query(States.payment_choice)
async def payment_choice(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    if callback_query.data == "back":
        await state.set_state(States.select_service)
        await answer_msg(
            msg_obj=callback_query,
            text=msg_text("select_service", profile.language),
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

    try:
        profile_record = await Cache.profile.get_record(profile.id)
    except ProfileNotFoundError:
        logger.warning(f"Profile record not found for profile {profile.id} in payment_choice.")
        await callback_query.answer(msg_text("profile_data_not_found_error", profile.language), show_alert=True)
        return

    await state.update_data(service_type=option, profile=profile_record.model_dump())
    await answer_msg(
        msg_obj=callback_query,
        text=msg_text("workout_type", profile.language),
        reply_markup=workout_type_kb(profile.language),
    )
    await state.set_state(States.workout_type)
    await del_msg(cast(Message | CallbackQuery | None, callback_query))


@payment_router.callback_query(States.handle_payment)
async def handle_payment(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    cb_data = callback_query.data or ""

    if cb_data == "back":
        await callback_query.answer()
        await show_balance_menu(callback_query, profile, state)
        return

    if cb_data != "done":
        return

    order_id = data.get("order_id")
    amount = data.get("amount")
    service_type = data.get("service_type")
    wishes = data.get("wishes", "")

    if not isinstance(order_id, str) or not isinstance(service_type, str):
        await callback_query.answer("Invalid payments data", show_alert=True)
        return

    try:
        amount = Decimal(str(amount)).quantize(Decimal("0.01"), ROUND_HALF_UP)
        if amount <= 0:
            raise ValueError
    except (InvalidOperation, TypeError, ValueError):
        await callback_query.answer("Invalid amount format", show_alert=True)
        return

    profile_data = data.get("profile")
    if not profile_data:
        await callback_query.answer(msg_text("profile_data_not_found_error", profile.language), show_alert=True)
        return
    selected_profile = Profile.model_validate(profile_data)

    if service_type == "program":
        required = int(data.get("required", 0))
        await APIService.profile.adjust_credits(profile.id, -required)
        await Cache.profile.update_record(selected_profile.id, {"credits": selected_profile.credits - required})
        await cache_program_data(data, selected_profile.id)
        await callback_query.answer(msg_text("payment_success", profile.language), show_alert=True)
        if callback_query.message:
            await show_main_menu(cast(Message, callback_query.message), profile, state)
        await del_msg(callback_query)
        return
    else:
        required = int(data.get("required", 0))
        price = Decimal(required)
        period_map = {
            "subscription_1_month": SubscriptionPeriod.one_month,
            "subscription_6_months": SubscriptionPeriod.six_months,
        }
        period = period_map.get(service_type, SubscriptionPeriod.one_month)
        subscription_id = await APIService.workout.create_subscription(
            profile_id=selected_profile.id,
            workout_days=data.get("workout_days", []),
            wishes=wishes,
            amount=price,
            period=period,
        )

        subscription_data = {
            "id": subscription_id,
            "payment_date": datetime.today().strftime("%Y-%m-%d"),
            "enabled": False,
            "price": price,
            "period": period.value,
            "profile": selected_profile.id,
            "workout_days": data.get("workout_days", []),
            "workout_type": data.get("workout_type"),
            "wishes": wishes,
        }
        await Cache.workout.update_subscription(selected_profile.id, subscription_data)

    await PaymentCacheManager.set_status(selected_profile.id, service_type, PaymentStatus.PENDING)
    await APIService.payment.create_payment(selected_profile.id, service_type, order_id, amount)
    await callback_query.answer(msg_text("payment_in_progress", profile.language), show_alert=True)

    msg = callback_query.message
    if msg and isinstance(msg, Message):
        await show_main_menu(msg, profile, state)

    await del_msg(callback_query)


@payment_router.callback_query(States.confirm_service)
async def confirm_service(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    if callback_query.data == "no":
        await show_my_workouts_menu(callback_query, profile, state)
        return

    service_type = data.get("service_type")
    if service_type == "subscription":
        await process_new_subscription(callback_query, profile, state, confirmed=True)
        return
