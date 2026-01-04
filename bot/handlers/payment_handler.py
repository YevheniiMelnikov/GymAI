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
from bot.texts import MessageText, translate

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
        await callback_query.answer(translate(MessageText.unexpected_error, profile.language), show_alert=True)
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
