from datetime import datetime
from decimal import InvalidOperation, Decimal, ROUND_HALF_UP
from typing import cast

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from loguru import logger

from bot.utils.bot import del_msg, answer_msg
from bot.keyboards import select_service_kb, workout_type_kb
from bot.utils.menus import has_human_coach_subscription
from bot.utils.profiles import get_assigned_coach
from bot.states import States

from core.cache import Cache
from core.cache.payment import PaymentCacheManager
from core.enums import ClientStatus, PaymentStatus, CoachType
from core.services import APIService
from bot.utils.menus import show_main_menu, show_services_menu
from core.schemas import Coach, Client
from apps.payments.tasks import send_client_request
from bot.utils.workout_plans import cache_program_data, process_new_subscription
from bot.texts import msg_text, btn_text
from core.schemas import Profile
from core.exceptions import ClientNotFoundError, CoachNotFoundError

payment_router = Router()


@payment_router.callback_query(States.gift)
async def get_the_gift(callback_query: CallbackQuery, state: FSMContext):
    if callback_query.data != "get":
        return

    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    await callback_query.answer(btn_text("done", profile.language))
    client = await Cache.client.get_client(profile.id)
    await Cache.client.update_client(client.profile, dict(status=ClientStatus.waiting_for_text))
    await answer_msg(
        msg_obj=callback_query,
        text=msg_text("workout_type", profile.language),
        reply_markup=workout_type_kb(profile.language),
    )
    await state.update_data(new_client=True)
    await state.set_state(States.workout_type)
    await del_msg(cast(Message | CallbackQuery | None, callback_query))


@payment_router.callback_query(States.payment_choice)
async def payment_choice(callback_query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    if callback_query.data == "back":
        await state.set_state(States.select_service)
        has_coach: bool = await has_human_coach_subscription(profile.id)
        await answer_msg(
            msg_obj=callback_query,
            text=msg_text("select_service", profile.language),
            reply_markup=select_service_kb(profile.language, has_coach),
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
        client = await Cache.client.get_client(profile.id)
        if not client.assigned_to:
            await callback_query.answer(msg_text("client_not_assigned_to_coach", profile.language), show_alert=True)
            return
        coach = await get_assigned_coach(client, coach_type=CoachType.human)
        if coach is None:
            await callback_query.answer(msg_text("coach_data_not_found_error", profile.language), show_alert=True)
            return

    except ClientNotFoundError:
        logger.warning(f"Client not found for profile {profile.id} in payment_choice.")
        await callback_query.answer(msg_text("client_data_not_found_error", profile.language), show_alert=True)
        return
    except CoachNotFoundError:
        logger.warning(f"Coach not found (ID from client.assigned_to) for profile {profile.id} in payment_choice.")
        await callback_query.answer(msg_text("coach_data_not_found_error", profile.language), show_alert=True)
        return

    await state.update_data(service_type=option, client=client.model_dump(), coach=coach.model_dump())
    await answer_msg(
        msg_obj=callback_query,
        text=msg_text("workout_type", profile.language),
        reply_markup=workout_type_kb(profile.language),
    )
    await state.set_state(States.workout_type)
    await del_msg(cast(Message | CallbackQuery | None, callback_query))


@payment_router.callback_query(States.handle_payment)
async def handle_payment(callback_query: CallbackQuery, state: FSMContext):
    if not callback_query.data == "done":
        return

    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
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

    try:
        client = await Cache.client.get_client(profile.id)
        if not client.assigned_to:
            await callback_query.answer(
                msg_text("client_not_assigned_to_coach", profile.language),
                show_alert=True,
            )
            return
        coach = await get_assigned_coach(client, coach_type=CoachType.human)
        if coach is None:
            await callback_query.answer(
                msg_text("coach_data_not_found_error", profile.language),
                show_alert=True,
            )
            return
    except ClientNotFoundError:
        logger.warning(f"Client not found for profile {profile.id}")
        await callback_query.answer(
            msg_text("client_data_not_found_error", profile.language),
            show_alert=True,
        )
        return
    except CoachNotFoundError:
        logger.warning(f"Coach not found for profile {profile.id}")
        await callback_query.answer(
            msg_text("coach_data_not_found_error", profile.language),
            show_alert=True,
        )
        return

    if service_type == "program":
        await cache_program_data(data, client.profile)
    else:
        price = coach.subscription_price or Decimal("0")
        period_map = {
            "subscription_1_month": "1m",
            "subscription_6_months": "6m",
        }
        period = period_map.get(service_type, "1m")
        subscription_id = await APIService.workout.create_subscription(
            client_profile_id=client.id,
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
            "period": period,
            "client_profile": client.profile,
            "workout_days": data.get("workout_days", []),
            "workout_type": data.get("workout_type"),
            "wishes": wishes,
        }
        await Cache.workout.update_program(client.profile, subscription_data)

    await PaymentCacheManager.set_status(client.profile, service_type, PaymentStatus.PENDING)
    await APIService.payment.create_payment(client.profile, service_type, order_id, amount)
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
        await show_services_menu(callback_query, profile, state)
        return

    service_type = data.get("service_type")
    if service_type == "subscription":
        await process_new_subscription(callback_query, profile, state, confirmed=True)
        return
    if service_type == "program":
        coach = Coach.model_validate(data.get("coach"))
        client = Client.model_validate(data.get("client"))
        required = int(data.get("required", 0))
        wishes = data.get("wishes", "")
        await APIService.profile.adjust_client_credits(profile.id, -required)
        await Cache.client.update_client(client.profile, {"credits": client.credits - required})
        payout = (coach.program_price or Decimal("0")).quantize(Decimal("0.01"), ROUND_HALF_UP)
        await APIService.profile.adjust_coach_payout_due(coach.profile, payout)
        new_due = (coach.payout_due or Decimal("0")) + payout
        await Cache.coach.update_coach(coach.profile, {"payout_due": str(new_due)})
        send_client_request.delay(  # pyrefly: ignore[not-callable]
            coach.profile,
            client.profile,
            {
                "service_type": "program",
                "workout_type": data.get("workout_type"),
                "wishes": wishes,
            },
        )
        await callback_query.answer(msg_text("payment_success", profile.language), show_alert=True)
        if callback_query.message:
            await show_main_menu(cast(Message, callback_query.message), profile, state)
        await del_msg(callback_query)
