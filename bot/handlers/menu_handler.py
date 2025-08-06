from __future__ import annotations


from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest
from contextlib import suppress
from typing import cast
from loguru import logger

from bot.keyboards import (
    select_workout_kb,
    choose_coach_kb,
    select_days_kb,
    gift_kb,
    yes_no_kb,
    workout_type_kb,
)
from bot.states import States
from bot.texts.text_manager import msg_text
from config.app_settings import settings
from bot.ai_coach.utils import assign_client
from core.cache import Cache
from core.enums import CoachType
from core.schemas import Coach, Client, Profile
from bot.utils.chat import contact_client, process_feedback_content
from bot.utils.menus import (
    show_main_menu,
    show_exercises_menu,
    manage_subscription,
    show_coaches_menu,
    show_profile_editing_menu,
    show_my_workouts_menu,
    show_my_clients_menu,
    show_my_profile_menu,
    show_subscription_history,
    clients_menu_pagination,
    show_services_menu,
    show_balance_menu,
    show_ai_services,
)
from bot.utils.menus import has_active_human_subscription
from bot.utils.profiles import assign_coach, get_assigned_coach
from bot.utils.workout_plans import manage_program, cancel_subscription
from bot.utils.other import del_msg, generate_order_id, answer_msg
from core.exceptions import ClientNotFoundError, SubscriptionNotFoundError
from core.services import APIService, ProfileService
from bot.keyboards import payment_kb
from bot.utils.credits import available_packages
from bot.ai_coach.utils import generate_subscription, generate_program
from bot.utils.credits import available_ai_services

menu_router = Router()


@menu_router.callback_query(States.main_menu)
async def main_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    message = callback_query.message
    if message is None or not isinstance(message, Message):
        return
    cb_data = callback_query.data or ""

    if cb_data == "feedback":
        await callback_query.answer()
        await message.answer(msg_text("feedback", profile.language))
        await state.set_state(States.feedback)
        await del_msg(message)

    elif cb_data == "my_profile":
        await show_my_profile_menu(callback_query, profile, state)

    elif cb_data == "my_clients":
        await show_my_clients_menu(callback_query, profile, state)

    elif cb_data == "my_workouts":
        await show_my_workouts_menu(callback_query, profile, state)

    elif cb_data == "services":
        await show_services_menu(callback_query, profile, state)


@menu_router.callback_query(States.choose_plan)
async def plan_choice(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data.get("profile"))
    cb_data = callback_query.data or ""

    if cb_data == "back":
        await show_services_menu(callback_query, profile, state)
        return

    if cb_data.startswith("plan_"):
        plan_name = cb_data.split("_", 1)[1]
        packages = {p.name: p for p in available_packages()}
        pkg = packages.get(plan_name)
        if not pkg:
            await callback_query.answer()
            return
        order_id = generate_order_id()
        await APIService.payment.create_payment(profile.id, "credits", order_id, pkg.price)
        link = await APIService.payment.get_payment_link(
            "pay",
            pkg.price,
            order_id,
            "credits",
            profile.id,
        )
        await state.set_state(States.handle_payment)
        await answer_msg(
            callback_query,
            msg_text("follow_link", profile.language),
            reply_markup=payment_kb(profile.language, link, "credits"),
        )
    await del_msg(callback_query)


@menu_router.callback_query(States.services_menu)
async def services_menu(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data.get("profile"))
    cb_data = callback_query.data or ""

    if cb_data == "back" and isinstance(callback_query.message, Message):
        await show_main_menu(callback_query.message, profile, state)
        return

    if cb_data == "balance":
        await show_balance_menu(callback_query, profile, state)
        return

    if cb_data == "ai_coach":
        coach = await Cache.coach.get_ai_coach()
        if not coach:
            await callback_query.answer(msg_text("no_coaches", profile.language), show_alert=True)
            return
        client = await Cache.client.get_client(profile.id)
        await state.update_data(ai_coach=coach.model_dump(mode="json"), client=client.model_dump())
        await show_ai_services(callback_query, profile, state)
        return

    if cb_data == "choose_coach":
        coaches = await Cache.coach.get_coaches()
        if not coaches:
            await callback_query.answer(msg_text("no_coaches", profile.language), show_alert=True)
            return

        await state.set_state(States.coach_selection)
        await state.update_data(coaches=[coach.model_dump(mode="json") for coach in coaches])
        message = cast(Message, callback_query.message)
        await show_coaches_menu(message, coaches, bot)
        return


@menu_router.callback_query(States.choose_ai_service)
async def ai_service_choice(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data.get("profile"))
    cb_data = callback_query.data or ""

    if cb_data == "back":
        await show_services_menu(callback_query, profile, state)
        return

    if cb_data.startswith("ai_plan_"):
        coach_data = data.get("ai_coach")
        client_data = data.get("client")
        if not coach_data or not client_data:
            await callback_query.answer(msg_text("unexpected_error", profile.language), show_alert=True)
            return
        coach = Coach.model_validate(coach_data)
        client = Client.model_validate(client_data)
        await assign_coach(coach, client)
        await callback_query.answer(msg_text("saved", profile.language))
        await state.set_state(States.workout_type)
        await answer_msg(
            callback_query,
            msg_text("workout_type", profile.language),
            reply_markup=workout_type_kb(profile.language),
        )
        await state.update_data(new_client=True)
        await del_msg(callback_query)
        return

    if cb_data.startswith("ai_service_"):
        client_data = data.get("client")
        if not client_data:
            await callback_query.answer(msg_text("unexpected_error", profile.language), show_alert=True)
            return
        client = Client.model_validate(client_data)

        service = cb_data.removeprefix("ai_service_")
        services = {s.name: s.credits for s in available_ai_services()}
        required = services.get(service, 0)
        if client.credits < required:
            await callback_query.answer(msg_text("not_enough_credits", profile.language), show_alert=True)
            await show_balance_menu(callback_query, profile, state)
            return

        workout_type = data.get("workout_type")
        await state.update_data(
            ai_service=service,
            required=required,
        )
        if workout_type is None:
            await state.set_state(States.workout_type)
            await answer_msg(
                callback_query,
                msg_text("workout_type", profile.language),
                reply_markup=workout_type_kb(profile.language),
            )
        else:
            await state.update_data(workout_type=workout_type)
            await state.set_state(States.enter_wishes)
            await answer_msg(callback_query, msg_text("enter_wishes", profile.language))
        await del_msg(callback_query)
        return


@menu_router.callback_query(States.ai_confirm_service)
async def ai_confirm_service(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data.get("profile"))
    client = Client.model_validate(data.get("client"))
    service = data.get("ai_service", "program")
    required = int(data.get("required", 0))
    workout_type = data.get("workout_type", "gym")
    wishes = data.get("wishes", "")

    if callback_query.data == "no":
        await show_main_menu(callback_query.message, profile, state)
        await del_msg(callback_query)
        return

    await ProfileService.adjust_client_credits(profile.id, -required)
    await Cache.client.update_client(client.profile, {"credits": client.credits - required})
    await answer_msg(callback_query, msg_text("request_in_progress", profile.language))
    await show_main_menu(callback_query.message, profile, state)
    bot = cast(Bot, callback_query.bot)
    assigned_coaches = [await Cache.coach.get_coach(coach_id) for coach_id in client.assigned_to]
    if any(coach.coach_type == CoachType.ai for coach in assigned_coaches):
        pass  # already assigned to AI
    else:
        await assign_coach(await Cache.coach.get_ai_coach(), client)
        await assign_client(client, profile.language)

    if service == "program":
        try:
            await generate_program(client, profile.language, workout_type, wishes, state, bot)
        except Exception as e:  # noqa: BLE001
            logger.exception(f"Program generation failed: {e}")
            await answer_msg(callback_query, msg_text("unexpected_error", profile.language))
        return

    period_map = {
        "subscription_1_month": "1m",
        "subscription_6_months": "6m",
    }
    await state.update_data(period=period_map.get(service, "1m"))
    await state.set_state(States.ai_workout_days)
    await answer_msg(
        callback_query,
        msg_text("select_days", profile.language),
        reply_markup=select_days_kb(profile.language, []),
    )
    await del_msg(cast(Message | CallbackQuery | None, callback_query))
    return


@menu_router.callback_query(States.ai_workout_days)
async def ai_workout_days(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data.get("profile"))
    lang = profile.language or settings.DEFAULT_LANGUAGE
    days: list[str] = data.get("workout_days", [])

    if callback_query.data != "complete":
        data_val = callback_query.data
        if data_val is not None:
            if data_val in days:
                days.remove(data_val)
            else:
                days.append(data_val)
        await state.update_data(workout_days=days)
        message = callback_query.message
        if message and isinstance(message, Message):
            with suppress(TelegramBadRequest):
                await message.edit_reply_markup(reply_markup=select_days_kb(lang, days))
        await state.set_state(States.ai_workout_days)
        return

    if not days:
        await callback_query.answer("❌")
        return

    await state.update_data(workout_days=days)
    client = Client.model_validate(data.get("client"))
    workout_type = data.get("workout_type", "gym")
    wishes = data.get("wishes", "")
    period = data.get("period", "1m")
    await answer_msg(callback_query, msg_text("request_in_progress", lang))
    await show_main_menu(callback_query.message, profile, state)
    await generate_subscription(client, lang, workout_type, wishes, period, days)


@menu_router.callback_query(States.profile)
async def profile_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    message = callback_query.message
    if message is None or not isinstance(message, Message):
        return
    cb_data = callback_query.data or ""

    if cb_data == "profile_edit":
        await show_profile_editing_menu(message, profile, state)
    elif cb_data == "back":
        await show_main_menu(message, profile, state)
    else:
        await message.answer(
            msg_text("delete_confirmation", profile.language),
            reply_markup=yes_no_kb(profile.language),
        )
        await del_msg(message)
        await state.set_state(States.profile_delete)


@menu_router.message(States.feedback)
async def handle_feedback(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)

    if await process_feedback_content(message, profile, bot):
        logger.info(f"Profile_id {profile.id} sent feedback")
        await message.answer(msg_text("feedback_sent", profile.language))
        await show_main_menu(message, profile, state)


@menu_router.callback_query(States.choose_coach)
async def choose_coach_menu(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    message = callback_query.message
    if message is None or not isinstance(message, Message):
        return
    cb_data = callback_query.data or ""

    if cb_data == "back":
        await show_main_menu(message, profile, state)
    elif cb_data == "ai_coach":
        coach = await Cache.coach.get_ai_coach()
        if not coach:
            await callback_query.answer(msg_text("no_coaches", profile.language), show_alert=True)
            return
        try:
            client = await Cache.client.get_client(profile.id)
        except ClientNotFoundError:
            await callback_query.answer(msg_text("unexpected_error", profile.language), show_alert=True)
            await del_msg(message)
            return
        await state.update_data(ai_coach=coach.model_dump(mode="json"), client=client.model_dump())
        await show_ai_services(callback_query, profile, state)
    else:
        coaches = await Cache.coach.get_coaches()
        if not coaches:
            await callback_query.answer(msg_text("no_coaches", profile.language), show_alert=True)
            return

        try:
            client = await Cache.client.get_client(profile.id)
        except ClientNotFoundError:
            client = None

        if client and client.assigned_to:
            human = await get_assigned_coach(client, coach_type=CoachType.human)
            if human:
                coaches = [c for c in coaches if c.profile != human.profile]

        await state.set_state(States.coach_selection)
        await state.update_data(coaches=[coach.model_dump(mode="json") for coach in coaches])
        await show_coaches_menu(message, coaches, bot)

    await del_msg(message)


@menu_router.callback_query(States.coach_selection)
async def paginate_coaches(cbq: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data.get("profile"))
    message: Message = cbq.message  # type: ignore
    if message is None:
        return

    cb_data = cbq.data or ""

    if cb_data == "quit":
        await message.answer(
            msg_text("no_program", profile.language),
            reply_markup=choose_coach_kb(profile.language),
        )
        await state.set_state(States.choose_coach)
        await del_msg(message)
        return

    if "_" not in cb_data:
        await cbq.answer(msg_text("out_of_range", profile.language))
        return

    action, param = cb_data.split("_", maxsplit=1)

    coaches = [Coach.model_validate(d) for d in data.get("coaches", [])]
    if not coaches:
        await cbq.answer(msg_text("no_coaches", profile.language))
        return

    if action in {"prev", "next"}:
        try:
            page = int(param)
        except ValueError:
            await message.answer(msg_text("out_of_range", profile.language))
            return

        if page < 0 or page >= len(coaches):
            await cbq.answer(msg_text("out_of_range", profile.language))
            return

        await show_coaches_menu(message, coaches, bot, current_index=page)
        return

    if action == "selected":
        try:
            coach_id = int(param)
        except ValueError:
            await message.answer(msg_text("unexpected_error", profile.language))
            return

        selected_coach = next((c for c in coaches if c.id == coach_id), None)
        if selected_coach is None:
            logger.warning("Coach not found for id %s", coach_id)
            await message.answer(msg_text("unexpected_error", profile.language))
            return

        try:
            client = await Cache.client.get_client(profile.id)
        except ClientNotFoundError:
            logger.warning("Client not found for profile_id %s", profile.id)
            await message.answer(msg_text("unexpected_error", profile.language))
            return

        if client.assigned_to:
            human = await get_assigned_coach(client, coach_type=CoachType.human)
            if human and human.profile == selected_coach.profile:
                await cbq.answer(msg_text("same_coach_selected", profile.language), show_alert=True)
                await del_msg(message)
                return

        if client.assigned_to:
            try:
                subscription = await Cache.workout.get_latest_subscription(profile.id)
            except SubscriptionNotFoundError:
                subscription = None
            if subscription and subscription.enabled:
                await cancel_subscription(profile.id, subscription.id)

        await assign_coach(selected_coach, client)
        await cbq.answer(msg_text("saved", profile.language))
        await state.set_state(States.gift)
        await message.answer(
            msg_text("gift", profile.language),
            reply_markup=gift_kb(profile.language),
        )
        await del_msg(message)
        return

    await message.answer(msg_text("unexpected_error", profile.language))


@menu_router.callback_query(States.show_clients)
async def client_paginator(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    message = callback_query.message
    if message is None or not isinstance(message, Message):
        return
    data_str = callback_query.data or ""

    if data_str == "back":
        await callback_query.answer()
        await show_main_menu(message, profile, state)
        return

    parts = data_str.split("_")
    if len(parts) != 2:
        await callback_query.answer(msg_text("out_of_range", profile.language))
        return

    action, profile_id_str = parts
    if action == "contact":
        await contact_client(callback_query, profile, profile_id_str, state)
        return
    if action == "program":
        await manage_program(callback_query, profile, profile_id_str, state)
        return
    if action == "subscription":
        await manage_subscription(callback_query, profile.language, profile_id_str, state)
        return

    try:
        index = int(profile_id_str)
    except ValueError:
        await callback_query.answer(msg_text("out_of_range", profile.language))
        return

    await clients_menu_pagination(callback_query, profile, index, state)


@menu_router.callback_query(States.show_subscription)
async def show_subscription_actions(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    message = callback_query.message
    if message is None or not isinstance(message, Message):
        return
    cb_data = callback_query.data or ""

    try:
        client = await Cache.client.get_client(profile.id)
    except ClientNotFoundError:
        logger.warning(f"Client not found for profile_id {profile.id}")
        await callback_query.answer(msg_text("unexpected_error", profile.language), show_alert=True)
        return

    if cb_data == "back":
        await callback_query.answer()
        await state.set_state(States.select_workout)
        contact = await has_active_human_subscription(profile.id)
        await message.answer(
            msg_text("select_workout", profile.language),
            reply_markup=select_workout_kb(profile.language, contact),
        )

    elif cb_data == "change_days":
        await callback_query.answer()
        await state.update_data(edit_mode=True)
        await state.set_state(States.workout_days)
        await message.answer(
            msg_text("select_days", profile.language),
            reply_markup=select_days_kb(profile.language, []),
        )

    elif cb_data == "history":
        await show_subscription_history(callback_query, profile, state)

    elif cb_data == "contact":
        await callback_query.answer()
        coach = await get_assigned_coach(client, coach_type=CoachType.human)
        if not coach:
            await callback_query.answer(msg_text("client_not_assigned_to_coach", profile.language), show_alert=True)
            return
        coach_id = coach.profile
        await state.update_data(recipient_id=coach_id, sender_name=client.name)
        await state.set_state(States.contact_coach)
        await message.answer(msg_text("enter_your_message", profile.language))

    elif cb_data == "cancel":
        logger.info(f"User {profile.id} requested to stop the subscription")
        await callback_query.answer(msg_text("subscription_canceled", profile.language), show_alert=True)

        if not callback_query.from_user:
            return
        subscription = await Cache.workout.get_latest_subscription(profile.id)
        if subscription is None:
            return

        await cancel_subscription(profile.id, subscription.id)
        logger.info(f"Subscription for client_id {client.id} deactivated")
        await show_main_menu(message, profile, state)

    else:
        await callback_query.answer()
        try:
            subscription = await Cache.workout.get_latest_subscription(profile.id)
        except SubscriptionNotFoundError:
            logger.warning(f"Subscription not found for client_id {client.id}")
            await callback_query.answer(msg_text("unexpected_error", profile.language), show_alert=True)
            return

        workout_days = subscription.workout_days
        await state.update_data(
            exercises=subscription.exercises,
            days=workout_days,
            split=len(workout_days),
        )
        await show_exercises_menu(callback_query, state, profile)

    await del_msg(message)
