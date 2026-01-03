from decimal import InvalidOperation, Decimal, ROUND_HALF_UP

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message


from bot.utils.bot import del_msg
from bot.states import States

from core.cache.payment import PaymentCacheManager
from core.enums import PaymentStatus
from core.services import APIService
from bot.utils.menus import show_main_menu, show_balance_menu
from core.schemas import Profile
from bot.utils.workout_plans import process_new_program, process_new_subscription
from bot.utils.split_number import DEFAULT_SPLIT_NUMBER, update_split_number_message
from bot.texts import MessageText, translate
from config.app_settings import settings

payment_router = Router()


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
        await callback_query.answer(
            translate(MessageText.profile_data_not_found_error, profile.language), show_alert=True
        )
        return
    selected_profile = Profile.model_validate(profile_data)

    if service_type != "credits":
        await callback_query.answer(translate(MessageText.unexpected_error, profile.language), show_alert=True)
        return

    await PaymentCacheManager.set_status(selected_profile.id, service_type, PaymentStatus.PENDING)
    await APIService.payment.create_payment(selected_profile.id, service_type, order_id, amount)
    await callback_query.answer(translate(MessageText.payment_in_progress, profile.language), show_alert=True)

    msg = callback_query.message
    if msg and isinstance(msg, Message):
        await show_main_menu(msg, profile, state)

    await del_msg(callback_query)


@payment_router.callback_query(States.confirm_service)
async def confirm_service(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    action = str(callback_query.data or "").lower()
    if action in {"no", "back"}:
        await callback_query.answer()
        count = int(data.get("split_number", DEFAULT_SPLIT_NUMBER))
        await state.set_state(States.split_number_selection)
        await update_split_number_message(callback_query, profile.language or settings.DEFAULT_LANG, count)
        return

    service_type = data.get("service_type")
    if service_type == "subscription":
        if action not in {"confirm_generate", "yes"}:
            await callback_query.answer()
            return
        await process_new_subscription(callback_query, profile, state, confirmed=True)
        return
    if service_type == "program":
        if action not in {"confirm_generate", "yes"}:
            await callback_query.answer()
            return
        await process_new_program(callback_query, profile, state, confirmed=True)
        return
    await callback_query.answer(translate(MessageText.unexpected_error, profile.language), show_alert=True)
