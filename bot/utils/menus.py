from __future__ import annotations

from contextlib import suppress
from datetime import datetime
from typing import cast

from loguru import logger
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto, Message, FSInputFile
from pathlib import Path

from bot import keyboards as kb
from bot.utils.profiles import fetch_user, answer_profile, get_assigned_coach
from bot.keyboards import program_view_kb, subscription_manage_kb, program_edit_kb
from bot.utils.credits import uah_to_credits, available_packages, available_ai_services
from decimal import Decimal
from bot.states import States
from bot.texts import msg_text
from core.cache import Cache
from core.enums import ClientStatus, CoachType
from core.exceptions import (
    ClientNotFoundError,
    CoachNotFoundError,
    SubscriptionNotFoundError,
    ProgramNotFoundError,
)
from core.schemas import Client, Coach, Profile, Subscription, Program, DayExercises, Exercise
from bot.utils.text import (
    get_client_page,
    get_profile_attributes,
    get_translated_week_day,
)
from bot.utils.exercises import format_program, format_full_program
from config.env_settings import settings
from bot.utils.other import answer_msg, del_msg
from core.services import avatar_manager
from core.validators import validate_or_raise


async def has_active_human_subscription(client_id: int) -> bool:
    try:
        subscription = await Cache.workout.get_latest_subscription(client_id)
    except SubscriptionNotFoundError:
        return False

    if not subscription or not subscription.enabled:
        return False

    try:
        client = await Cache.client.get_client(client_id)
        if not client.assigned_to:
            return False
        coach = await get_assigned_coach(client, coach_type=CoachType.human)
        return coach is not None
    except Exception:
        return False

async def show_subscription_page(callback_query: CallbackQuery, state: FSMContext, subscription: Subscription) -> None:
    await callback_query.answer()
    profile = await Cache.profile.get_profile(callback_query.from_user.id)
    assert profile is not None
    lang = cast(str, profile.language)

    next_payment_date_str = subscription.payment_date
    enabled_status = "✅" if subscription.enabled else "❌"
    translated_week_days = ", ".join(get_translated_week_day(lang, x) for x in subscription.workout_days)

    await state.set_state(States.show_subscription)
    message = callback_query.message

    if message and isinstance(message, Message):
        await answer_msg(
            message,
            msg_text("subscription_page", lang).format(
                next_payment_date=next_payment_date_str,
                enabled=enabled_status,
                price=subscription.price,
                days=translated_week_days,
            ),
            reply_markup=kb.show_subscriptions_kb(lang),
        )
        await del_msg(message)


async def show_profile_editing_menu(message: Message, profile: Profile, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(lang=profile.language)

    user_profile: Client | Coach | None = None
    reply_markup = None

    if profile.role == "client":
        try:
            user_profile = await Cache.client.get_client(profile.id)
            reply_markup = kb.edit_client_profile_kb(profile.language)
        except ClientNotFoundError:
            logger.info(f"Client data not found for profile {profile.id} during profile editing setup.")
        await state.update_data(role="client")
    else:
        try:
            user_profile = await Cache.coach.get_coach(profile.id)
            reply_markup = kb.edit_coach_profile_kb(profile.language)
        except CoachNotFoundError:
            logger.info(f"Coach data not found for profile {profile.id} during profile editing setup.")
        await state.update_data(role="coach")

    state_to_set = States.edit_profile if user_profile else States.name
    response_text = "choose_profile_parameter" if user_profile else "edit_profile"

    profile_msg = await answer_msg(
        message,
        msg_text(response_text, profile.language),
        reply_markup=reply_markup,
    )
    if profile_msg is None:
        logger.error("Failed to send profile editing menu message")
        return

    with suppress(TelegramBadRequest):
        await del_msg(cast(Message | CallbackQuery | None, message))

    await state.update_data(message_ids=[profile_msg.message_id], chat_id=message.chat.id)
    await state.set_state(state_to_set)

    if not user_profile:
        name_msg = await answer_msg(message, msg_text("name", profile.language))
        if name_msg is not None:
            await state.update_data(message_ids=[profile_msg.message_id, name_msg.message_id])


async def show_main_menu(message: Message, profile: Profile, state: FSMContext) -> None:
    menu = kb.client_menu_kb if profile.role == "client" else kb.coach_menu_kb
    await state.clear()
    await state.update_data(profile=profile.model_dump())
    await state.set_state(States.main_menu)
    await answer_msg(message, msg_text("main_menu", profile.language), reply_markup=menu(profile.language))
    await del_msg(cast(Message | CallbackQuery | None, message))


async def show_services_menu(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    lang = cast(str, profile.language)
    await callback_query.answer()
    await state.set_state(States.services_menu)
    await answer_msg(
        callback_query,
        msg_text("services_menu", lang),
        reply_markup=kb.services_menu_kb(lang),
    )
    await del_msg(callback_query)


async def show_balance_menu(callback_obj: CallbackQuery | Message, profile: Profile, state: FSMContext) -> None:
    lang = cast(str, profile.language)
    client = await Cache.client.get_client(profile.id)
    plans = [p.name for p in available_packages()]
    file_path = Path(settings.BOT_PAYMENT_OPTIONS) / f"credit_packages_{lang}.png"
    packages_img = FSInputFile(file_path)
    if isinstance(callback_obj, CallbackQuery):
        await callback_obj.answer()
    await state.set_state(States.choose_plan)
    await answer_msg(
        callback_obj,
        caption=(
            msg_text("credit_balance", lang).format(credits=client.credits) + "\n" + msg_text("tariff_plans", lang)
        ),
        photo=packages_img,
        reply_markup=kb.tariff_plans_kb(lang, plans),
    )
    await del_msg(callback_obj)


async def show_tariff_plans(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    language = cast(str, profile.language)
    plans = [p.name for p in available_packages()]
    await callback_query.answer()
    await state.set_state(States.choose_plan)
    file_path = Path(settings.BOT_PAYMENT_OPTIONS) / f"credit_packages_{language}.png"
    packages_img = FSInputFile(file_path)
    await answer_msg(
        callback_query,
        caption=msg_text("tariff_plans", language),
        photo=packages_img,
        reply_markup=kb.tariff_plans_kb(language, plans),
    )
    await del_msg(callback_query)


async def send_policy_confirmation(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)

    info_msg = await answer_msg(
        message,
        msg_text("contract_info_message", lang).format(
            public_offer=settings.PUBLIC_OFFER,
            privacy_policy=settings.PRIVACY_POLICY,
        ),
        disable_web_page_preview=True,
    )
    confirm_msg = await answer_msg(
        message,
        msg_text("accept_policy", lang),
        reply_markup=kb.yes_no_kb(lang),
    )
    message_ids: list[int] = []
    if info_msg:
        message_ids.append(info_msg.message_id)
    if confirm_msg:
        message_ids.append(confirm_msg.message_id)
    await state.update_data(chat_id=message.chat.id, message_ids=message_ids)
    await del_msg(message)


async def show_clients(message: Message, clients: list[Client], state: FSMContext, current_index: int = 0) -> None:
    profile = await Cache.profile.get_profile(message.chat.id)
    assert profile is not None
    language = cast(str, profile.language)

    current_index %= len(clients)
    current_client = clients[current_index]
    try:
        subscription = await Cache.workout.get_latest_subscription(current_client.profile)
    except SubscriptionNotFoundError:
        subscription = None

    subscription_active = subscription is not None
    data = await state.get_data()
    client_page = await get_client_page(current_client, language, subscription_active, data)

    await state.update_data(clients=[Client.model_dump(c) for c in clients])
    await message.edit_text(
        msg_text("client_page", language).format(**client_page),
        reply_markup=kb.client_select_kb(language, current_client.profile, current_index),
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(States.show_clients)


async def show_coaches_menu(message: Message, coaches: list[Coach], bot: Bot, current_index: int = 0) -> None:
    profile = await Cache.profile.get_profile(message.chat.id)
    assert profile is not None
    lang = cast(str, profile.language)

    if not coaches:
        await answer_msg(message, msg_text("no_coaches", lang))
        return

    current_index %= len(coaches)
    current_coach = coaches[current_index]
    coach_photo_url: str | FSInputFile
    if current_coach.coach_type == CoachType.ai or not current_coach.profile_photo:
        file_path = Path(__file__).resolve().parent.parent / "images" / "ai_coach.png"
        coach_photo_url = FSInputFile(file_path)
    else:
        coach_photo_url = f"https://storage.googleapis.com/{avatar_manager.bucket_name}/{current_coach.profile_photo}"
    formatted_text = msg_text("coach_page", lang).format(**current_coach.model_dump(mode="json"))

    if await has_active_human_subscription(profile.id):
        formatted_text += "\n" + msg_text("coach_switch_warning", lang)

    try:
        media = InputMediaPhoto(media=coach_photo_url)
        if message.photo:
            await message.edit_media(media=media)
            await message.edit_caption(
                caption=formatted_text,
                reply_markup=kb.coach_select_kb(lang, current_coach.id, current_index),
                parse_mode=ParseMode.HTML,
            )
        else:
            await bot.send_photo(
                message.chat.id,
                photo=coach_photo_url,
                caption=formatted_text,
                reply_markup=kb.coach_select_kb(lang, current_coach.id, current_index),
                parse_mode=ParseMode.HTML,
            )
    except TelegramBadRequest:
        await answer_msg(
            message,
            text=formatted_text,
            reply_markup=kb.coach_select_kb(lang, current_coach.id, current_index),
            parse_mode=ParseMode.HTML,
        )
        await del_msg(cast(Message | CallbackQuery | None, message))


async def show_my_profile_menu(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    user = await fetch_user(profile)
    lang = cast(str, profile.language)

    if profile.role == "client" and isinstance(user, Client):
        if user.status == ClientStatus.initial:
            await callback_query.answer(msg_text("finish_registration_to_get_credits", lang), show_alert=True)
            await state.set_state(States.workout_goals)
            msg = await answer_msg(callback_query, msg_text("workout_goals", lang))
            if msg is not None:
                await state.update_data(chat_id=callback_query.from_user.id, message_ids=[msg.message_id])
            await del_msg(cast(Message | CallbackQuery | None, callback_query))
            return

    text = msg_text(
        "client_profile" if profile.role == "client" else "coach_profile",
        lang,
    ).format(**get_profile_attributes(role=profile.role, user=user, lang=lang))

    await answer_profile(callback_query, profile, user, text)
    await state.set_state(States.profile)
    await del_msg(cast(Message | CallbackQuery | None, callback_query))


async def show_my_clients_menu(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    lang = cast(str, profile.language)
    coach = await Cache.coach.get_coach(profile.id)
    assert coach
    assigned_ids = coach.assigned_to if coach.assigned_to else []

    if assigned_ids:
        await callback_query.answer()
        clients: list[Client] = []
        for cid in assigned_ids:
            try:
                client = await Cache.client.get_client(cid)
                clients.append(client)
            except ClientNotFoundError:
                logger.warning(f"Client data not found for ID {cid} while listing coach's clients. Skipping.")

        if not clients:
            await callback_query.answer(msg_text("no_clients", lang), show_alert=True)
            await state.set_state(States.main_menu)
            return

        message = cast(Message, callback_query.message)
        assert message
        await show_clients(message, clients, state)
    else:
        if not coach.verified:
            await callback_query.answer(msg_text("coach_info_message", lang), show_alert=True)
        await callback_query.answer(msg_text("no_clients", lang), show_alert=True)
        await state.set_state(States.main_menu)


async def show_my_workouts_menu(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    lang = cast(str, profile.language)

    try:
        client = await Cache.client.get_client(profile.id)
    except ClientNotFoundError:
        logger.error(f"Client data not found for profile {profile.id} in show_my_workouts_menu.")
        await callback_query.answer(msg_text("questionnaire_not_completed", lang), show_alert=True)
        message = cast(Message, callback_query.message)
        assert message
        await show_profile_editing_menu(message, profile, state)
        return

    message = cast(Message, callback_query.message)
    assert message

    if client.status == ClientStatus.initial:
        await callback_query.answer(msg_text("finish_registration_to_get_credits", lang), show_alert=True)
        await state.set_state(States.workout_goals)
        msg = await answer_msg(callback_query, msg_text("workout_goals", lang))
        if msg is not None:
            await state.update_data(chat_id=callback_query.from_user.id, message_ids=[msg.message_id])
        return

    contact = await has_active_human_subscription(profile.id)

    await state.set_state(States.select_workout)
    await answer_msg(
        message,
        msg_text("select_workout", lang),
        reply_markup=kb.select_workout_kb(lang, contact),
    )

    await del_msg(cast(Message | CallbackQuery | None, message))


async def show_my_subscription_menu(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    language = cast(str, profile.language)
    message = cast(Message, callback_query.message)
    assert message

    try:
        subscription = await Cache.workout.get_latest_subscription(profile.id)
    except SubscriptionNotFoundError:
        subscription = None

    if not subscription or not subscription.enabled:
        file_path = Path(settings.BOT_PAYMENT_OPTIONS) / f"subscription_{language}.jpeg"
        subscription_img = FSInputFile(file_path)
        client_profile = await Cache.client.get_client(profile.id)
        if not client_profile.assigned_to:
            await callback_query.answer(msg_text("client_not_assigned_to_coach", language), show_alert=True)
            return

        await callback_query.answer()
        coach = await get_assigned_coach(client_profile, coach_type=CoachType.human)
        if coach is None:
            await callback_query.answer(msg_text("client_not_assigned_to_coach", language), show_alert=True)
            return
        price_uah = coach.subscription_price or Decimal("0")
        credits = uah_to_credits(price_uah)
        await state.set_state(States.payment_choice)
        await answer_msg(
            message,
            caption=msg_text("subscription_price", language).format(price=credits),
            photo=subscription_img,
            reply_markup=kb.choose_payment_options_kb(language, "subscription"),
        )
        await del_msg(cast(Message | CallbackQuery | None, message))
    else:
        if subscription.exercises:
            await state.update_data(exercises=subscription.exercises, subscription=True)
            await show_subscription_page(callback_query, state, subscription)
            return

        else:
            await callback_query.answer(msg_text("program_not_ready", language), show_alert=True)
            return


async def show_my_program_menu(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    message = cast(Message, callback_query.message)
    assert message
    client = await Cache.client.get_client(profile.id)

    try:
        program = await Cache.workout.get_latest_program(client.profile)
    except ProgramNotFoundError:
        program = None

    if program:
        if not program.exercises_by_day:
            await callback_query.answer(msg_text("program_not_ready", profile.language), show_alert=True)
            return

        await answer_msg(
            message,
            msg_text("select_action", profile.language),
            reply_markup=kb.program_action_kb(profile.language),
        )
        await state.update_data(program=program.model_dump())
        await state.set_state(States.program_action_choice)
        await del_msg(cast(Message | CallbackQuery | None, message))
    else:
        await show_program_promo_page(callback_query, profile, state)


async def show_program_promo_page(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    client_profile = await Cache.client.get_client(profile.id)
    language = cast(str, profile.language)

    if not client_profile.assigned_to:
        await callback_query.answer(msg_text("client_not_assigned_to_coach", language), show_alert=True)
        return

    await callback_query.answer()
    coach = await get_assigned_coach(client_profile, coach_type=CoachType.human)
    if coach is None:
        await callback_query.answer(msg_text("client_not_assigned_to_coach", language), show_alert=True)
        return
    file_path = Path(settings.BOT_PAYMENT_OPTIONS) / f"program_{language}.jpeg"
    program_img = FSInputFile(file_path)
    price_uah = coach.program_price or Decimal("0")
    credits = uah_to_credits(price_uah)
    message = cast(Message, callback_query.message)
    assert message

    await answer_msg(
        message,
        caption=msg_text("program_price", language).format(price=credits),
        photo=program_img,
        reply_markup=kb.choose_payment_options_kb(language, "program"),
    )
    await del_msg(cast(Message | CallbackQuery | None, message))
    await state.set_state(States.payment_choice)


async def show_ai_services(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    language = cast(str, profile.language)
    client = await Cache.client.get_client(profile.id)
    if client.status == ClientStatus.initial:
        await callback_query.answer(msg_text("finish_registration_to_get_credits", language), show_alert=True)
    else:
        await callback_query.answer()
    file_path = Path(__file__).resolve().parent.parent / "images" / "ai_coach.png"
    services = available_ai_services()
    await state.set_state(States.choose_ai_service)
    await answer_msg(
        callback_query,
        caption=msg_text("ai_services", language).format(balance=client.credits),
        photo=FSInputFile(file_path),
        reply_markup=kb.ai_services_kb(language, [p.name for p in services]),
    )
    await del_msg(callback_query)


async def show_exercises_menu(callback_query: CallbackQuery, state: FSMContext, profile: Profile) -> None:
    data = await state.get_data()
    exercises_data = data.get("exercises", [])
    exercises = [DayExercises.model_validate(e) for e in exercises_data]

    program = await format_program(exercises, day=0)
    days = data.get("days", [])
    week_day = get_translated_week_day(profile.language, days[0]).lower() if days else ""

    message = cast(Message, callback_query.message)
    assert message

    language = cast(str, profile.language)

    await answer_msg(
        message,
        msg_text("program_page", language).format(program=program, day=week_day),
        reply_markup=kb.program_view_kb(language),
        disable_web_page_preview=True,
    )

    await state.update_data(client=True, day_index=0)
    await state.set_state(States.program_view)
    await del_msg(cast(Message | CallbackQuery | None, message))


async def manage_subscription(callback_query: CallbackQuery, lang: str, profile_id: str, state: FSMContext) -> None:
    await state.clear()
    subscription = await Cache.workout.get_latest_subscription(int(profile_id))
    assert subscription
    message = cast(Message, callback_query.message)
    assert message

    if not subscription or not subscription.enabled:
        await callback_query.answer(msg_text("payment_required", lang), show_alert=True)
        await state.set_state(States.show_clients)
        return

    await callback_query.answer()
    days = subscription.workout_days
    week_day = get_translated_week_day(lang, days[0]).lower()

    if not subscription.exercises:
        await answer_msg(message, msg_text("no_program", lang))
        workouts_per_week = len(days)
        await answer_msg(message, msg_text("workouts_per_week", lang).format(days=workouts_per_week))
        await answer_msg(message, msg_text("program_guide", lang))
        day_1_msg = await answer_msg(
            message,
            msg_text("enter_daily_program", lang).format(day=week_day),
            reply_markup=kb.program_manage_kb(lang, workouts_per_week),
        )
        assert day_1_msg
        await state.update_data(
            chat_id=message.chat.id,
            message_ids=[day_1_msg.message_id],
            split=workouts_per_week,
            days=days,
            day_index=0,
            exercises={},
            client_id=profile_id,
            subscription=True,
        )
        await state.set_state(States.program_manage)
    else:
        program_text = await format_program(subscription.exercises, 0)
        await answer_msg(
            message,
            msg_text("program_page", lang).format(program=program_text, day=week_day),
            reply_markup=kb.subscription_manage_kb(lang),
            disable_web_page_preview=True,
        )
        await state.update_data(
            exercises=subscription.exercises,
            days=days,
            client_id=profile_id,
            day_index=0,
            subscription=True,
        )
        await state.set_state(States.subscription_manage)

    await del_msg(cast(Message | CallbackQuery | None, message))


async def clients_menu_pagination(
    callback_query: CallbackQuery, profile: Profile, index: int, state: FSMContext
) -> None:
    data = await state.get_data()
    clients = [
        validate_or_raise(client_data, Client, context="clients list") for client_data in data.get("clients", [])
    ]

    if not clients:
        await callback_query.answer(msg_text("no_clients", profile.language))
        return

    if index < 0 or index >= len(clients):
        await callback_query.answer(msg_text("out_of_range", profile.language))
        return

    message = callback_query.message
    if message and isinstance(message, Message):
        await show_clients(message, clients, state, index)


async def program_menu_pagination(state: FSMContext, callback_query: CallbackQuery) -> None:
    profile = await Cache.profile.get_profile(callback_query.from_user.id)
    assert profile is not None

    if callback_query.data == "quit":
        await show_my_clients_menu(callback_query, profile, state)
        return

    data = await state.get_data()
    current_day = data.get("day_index", 0)
    exercises = data.get("exercises", [])

    if isinstance(exercises, dict):
        exercises = [
            DayExercises(day=k, exercises=[Exercise.model_validate(e) if isinstance(e, dict) else e for e in v])
            for k, v in exercises.items()
        ]

    split_number = data.get("split")
    assert split_number is not None

    if data.get("client"):
        reply_markup = program_view_kb(profile.language)
        state_to_set = States.program_view
    else:
        reply_markup = (
            subscription_manage_kb(profile.language) if data.get("subscription") else program_edit_kb(profile.language)
        )
        state_to_set = States.subscription_manage if data.get("subscription") else States.program_edit

    await state.set_state(state_to_set)
    current_day += -1 if callback_query.data in ["prev_day", "previous"] else 1

    if current_day < 0 or current_day >= split_number:
        current_day = max(0, min(current_day, split_number - 1))
        await callback_query.answer(msg_text("out_of_range", profile.language))
        await state.update_data(day_index=current_day)
        return

    await state.update_data(day_index=current_day)

    program_text = await format_program(exercises, current_day)
    days = data.get("days", [])
    next_day = (
        get_translated_week_day(profile.language, days[current_day]).lower()
        if data.get("subscription")
        else current_day + 1
    )
    with suppress(TelegramBadRequest):
        message = callback_query.message
        if message and isinstance(message, Message):
            await message.edit_text(
                msg_text("program_page", profile.language).format(program=program_text, day=next_day),
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )

    await callback_query.answer()


async def show_program_history(
    callback_query: CallbackQuery,
    profile: Profile,
    state: FSMContext,
    index: int = 0,
) -> None:
    programs = await Cache.workout.get_all_programs(profile.id)
    if not programs:
        await callback_query.answer(msg_text("no_program", profile.language), show_alert=True)
        return

    index %= len(programs)
    program = programs[index]
    program_text = await format_full_program(program.exercises_by_day)
    date = datetime.fromtimestamp(program.created_at).strftime("%Y-%m-%d")

    await state.update_data(programs_history=[p.model_dump() for p in programs])
    await state.set_state(States.program_history)

    message = callback_query.message
    if message and isinstance(message, Message):
        await message.edit_text(
            msg_text("program_history_page", profile.language).format(program=program_text, date=date),
            reply_markup=kb.history_nav_kb(profile.language, "ph", index),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


async def program_history_pagination(
    callback_query: CallbackQuery,
    profile: Profile,
    index: int,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    programs_data = data.get("programs_history", [])
    programs = [Program.model_validate(p) for p in programs_data]

    if not programs:
        await callback_query.answer(msg_text("no_program", profile.language))
        return

    if index < 0 or index >= len(programs):
        await callback_query.answer(msg_text("out_of_range", profile.language))
        return

    program = programs[index]
    program_text = await format_full_program(program.exercises_by_day)
    date = datetime.fromtimestamp(program.created_at).strftime("%Y-%m-%d")

    message = callback_query.message
    if message and isinstance(message, Message):
        await message.edit_text(
            msg_text("program_history_page", profile.language).format(program=program_text, date=date),
            reply_markup=kb.history_nav_kb(profile.language, "ph", index),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    await callback_query.answer()


async def show_subscription_history(
    callback_query: CallbackQuery,
    profile: Profile,
    state: FSMContext,
    index: int = 0,
) -> None:
    subscriptions = await Cache.workout.get_all_subscriptions(profile.id)
    if not subscriptions:
        await callback_query.answer(msg_text("subscription_canceled", profile.language), show_alert=True)
        return

    index %= len(subscriptions)
    sub = subscriptions[index]
    program_text = await format_full_program(sub.exercises)
    date = sub.payment_date

    await state.update_data(subscriptions_history=[s.model_dump() for s in subscriptions])
    await state.set_state(States.subscription_history)

    message = callback_query.message
    if message and isinstance(message, Message):
        await message.edit_text(
            msg_text("subscription_history_page", profile.language).format(program=program_text, date=date),
            reply_markup=kb.history_nav_kb(profile.language, "sh", index),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


async def subscription_history_pagination(
    callback_query: CallbackQuery,
    profile: Profile,
    index: int,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    subs_data = data.get("subscriptions_history", [])
    subscriptions = [Subscription.model_validate(s) for s in subs_data]

    if not subscriptions:
        await callback_query.answer(msg_text("subscription_canceled", profile.language))
        return

    if index < 0 or index >= len(subscriptions):
        await callback_query.answer(msg_text("out_of_range", profile.language))
        return

    sub = subscriptions[index]
    program_text = await format_full_program(sub.exercises)
    date = sub.payment_date
    message = callback_query.message
    if message and isinstance(message, Message):
        await message.edit_text(
            msg_text("subscription_history_page", profile.language).format(program=program_text, date=date),
            reply_markup=kb.history_nav_kb(profile.language, "sh", index),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    await callback_query.answer()
