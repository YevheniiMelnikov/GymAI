from contextlib import suppress
from datetime import datetime

from loguru import logger
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto, Message
from dateutil.relativedelta import relativedelta

from bot.keyboards import *
from bot.states import States
from core.cache import Cache
from core.exceptions import UserServiceError
from core.services import APIService
from core.services.outer.gstorage_service import avatar_manager
from functions import profiles
from core.models import Client, Coach, Profile, Subscription
from functions.text_utils import (
    get_client_page,
    get_profile_attributes,
    format_program,
    get_translated_week_day,
)
from config.env_settings import Settings
from bot.texts.text_manager import msg_text
from functions.utils import fetch_user, answer_profile


async def show_subscription_page(callback_query: CallbackQuery, state: FSMContext, subscription: Subscription) -> None:
    await callback_query.answer()
    profile = await profiles.get_user_profile(callback_query.from_user.id)
    payment_date = datetime.strptime(subscription.payment_date, "%Y-%m-%d")
    next_payment_date = payment_date + relativedelta(months=1)
    next_payment_date_str = next_payment_date.strftime("%Y-%m-%d")
    enabled_status = "✅" if subscription.enabled else "❌"
    translated_week_days = ", ".join(
        map(lambda x: get_translated_week_day(profile.language, x), subscription.workout_days)
    )
    await state.set_state(States.show_subscription)
    await callback_query.message.answer(
        msg_text("subscription_page", profile.language).format(
            next_payment_date=next_payment_date_str,
            enabled=enabled_status,
            price=subscription.price,
            days=translated_week_days,
        ),
        reply_markup=show_subscriptions_kb(profile.language),
    )
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


async def show_profile_editing_menu(message: Message, profile: Profile, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(lang=profile.language)

    if profile.status == "client":
        try:
            user_profile = await Cache.client.get_client(profile.id)
        except UserServiceError as error:
            logger.error(f"Error retrieving client profile for {profile.id}: {error}")
            user_profile = None
        reply_markup = edit_client_profile_kb(profile.language) if user_profile else None
        await state.update_data(status="client")

    else:
        try:
            user_profile = await Cache.coach.get_coach(profile.id)
        except UserServiceError as error:
            logger.error(f"Error retrieving coach profile for {profile.id}: {error}")
            user_profile = None
        reply_markup = edit_coach_profile_kb(profile.language) if user_profile else None
        await state.update_data(status="coach")

    state_to_set = States.edit_profile if user_profile else States.name
    response_message = "choose_profile_parameter" if user_profile else "edit_profile"
    profile_msg = await message.answer(text=msg_text(response_message, profile.language), reply_markup=reply_markup)
    with suppress(TelegramBadRequest):
        await message.delete()
    await state.update_data(message_ids=[profile_msg.message_id], chat_id=message.chat.id)
    await state.set_state(state_to_set)

    if not user_profile:
        name_msg = await message.answer(msg_text("name", profile.language))
        await state.update_data(message_ids=[profile_msg.message_id, name_msg.message_id])


async def show_main_menu(message: Message, profile: Profile, state: FSMContext) -> None:
    menu = client_menu_kb if profile.status == "client" else coach_menu_kb
    await state.clear()
    await state.update_data(profile=profile.to_dict())
    await state.set_state(States.main_menu)
    await message.answer(msg_text("main_menu", profile.language), reply_markup=menu(profile.language))
    with suppress(TelegramBadRequest):
        await message.delete()


async def show_clients(message: Message, clients: list[Client], state: FSMContext, current_index=0) -> None:
    profile = await profiles.get_user_profile(message.chat.id)
    current_index %= len(clients)
    current_client = clients[current_index]
    subscription = True if await Cache.workout.get_subscription(current_client.id) else False
    data = await state.get_data()
    client_info = await get_client_page(current_client, profile.language, subscription, data)
    client_data = [Client.model_dump(client) for client in clients]

    await state.update_data(clients=client_data)
    await message.edit_text(
        msg_text("client_page", profile.language).format(**client_info),
        reply_markup=client_select_kb(profile.language, current_client.id, current_index),
        parse_mode="HTML",
    )
    await state.set_state(States.show_clients)


async def show_coaches_menu(message: Message, coaches: list[Coach], bot: Bot, current_index=0) -> None:
    profile = await profiles.get_user_profile(message.chat.id)
    current_index %= len(coaches)
    current_coach = coaches[current_index]
    text = msg_text("coach_page", profile.language)
    coach_photo_url = f"https://storage.googleapis.com/{avatar_manager.bucket_name}/{current_coach.profile_photo}"
    formatted_text = text.format(**current_coach.to_dict())

    try:
        media = InputMediaPhoto(media=coach_photo_url)
        if message.photo:
            await message.edit_media(media=media)
            await message.edit_caption(
                caption=formatted_text,
                reply_markup=coach_select_kb(profile.language, current_coach.id, current_index),
                parse_mode=ParseMode.HTML,
            )
        else:
            await bot.send_photo(
                message.chat.id,
                photo=coach_photo_url,
                caption=formatted_text,
                reply_markup=coach_select_kb(profile.language, current_coach.id, current_index),
                parse_mode=ParseMode.HTML,
            )
    except TelegramBadRequest:
        await message.answer(
            text=formatted_text,
            reply_markup=coach_select_kb(profile.language, current_coach.id, current_index),
            parse_mode=ParseMode.HTML,
        )
        with suppress(TelegramBadRequest):
            await message.delete()


async def show_my_profile_menu(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    user = await fetch_user(profile)
    text = msg_text(
        "client_profile" if profile.status == "client" else "coach_profile",
        profile.language,
    ).format(**get_profile_attributes(status=profile.status, user=user, lang=profile.language))

    await answer_profile(callback_query, profile, user, text)
    await state.set_state(States.profile)
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


async def my_clients_menu(callback_query: CallbackQuery, coach_profile: Profile, state: FSMContext) -> None:
    try:
        coach = await Cache.coach.get_coach(coach_profile.id)
        assigned_ids = coach.assigned_to if coach.assigned_to else None
    except UserServiceError as error:
        logger.error(f"Error retrieving coach data for profile {coach_profile.id}: {error}")
        await callback_query.answer(msg_text("coach_info_message", coach_profile.language), show_alert=True)
        return

    if assigned_ids:
        await callback_query.answer()
        try:
            clients = [await Cache.client.get_client(client) for client in assigned_ids]
        except UserServiceError as error:
            logger.error(f"Error retrieving client data for assigned IDs {assigned_ids}: {error}")
            clients = []
            for profile_id in assigned_ids:
                try:
                    if client_profile := await APIService.profile.get_profile(profile_id):
                        clients.append(client_profile)
                except Exception as e:
                    logger.error(f"Error retrieving profile data for client {profile_id}: {e}")
                    continue
        await show_clients(callback_query.message, clients, state)
    else:
        if not coach.verified:
            await callback_query.answer(msg_text("coach_info_message", coach_profile.language), show_alert=True)
        await callback_query.answer(msg_text("no_clients", coach_profile.language), show_alert=True)
        await state.set_state(States.main_menu)
        return


async def show_my_workouts_menu(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    try:
        client = await Cache.client.get_client(profile.id)
    except UserServiceError as error:
        logger.error(f"Error retrieving client data for profile {profile.id}: {error}")
        await callback_query.answer(msg_text("questionnaire_not_completed", profile.language), show_alert=True)
        await show_profile_editing_menu(callback_query.message, profile, state)
        return

    if not client.assigned_to:
        await callback_query.message.answer(
            msg_text("no_program", profile.language),
            reply_markup=choose_coach_kb(profile.language),
        )
        await state.set_state(States.choose_coach)
    else:
        await state.set_state(States.select_service)
        await callback_query.message.answer(
            msg_text("select_service", profile.language),
            reply_markup=select_service_kb(profile.language),
        )

    with suppress(TelegramBadRequest):
        try:
            await callback_query.message.delete()
        except TelegramBadRequest as e:
            logger.warning(f"Failed to delete message for callback {callback_query.id}: {e}")


async def show_my_subscription_menu(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    if await Cache.workout.check_payment_status(profile.id, "subscription"):
        await callback_query.answer(msg_text("program_not_ready", profile.language), show_alert=True)
        return

    subscription = await Cache.workout.get_subscription(profile.id)
    if not subscription or not subscription.enabled:
        subscription_img = Settings.BOT_PAYMENT_OPTIONS + f"subscription_{profile.language}.jpeg"
        client_profile = await Cache.client.get_client(profile.id)
        coach = await Cache.coach.get_coach(client_profile.assigned_to.pop())
        try:
            await callback_query.message.answer_photo(
                caption=msg_text("subscription_price", profile.language).format(price=coach.subscription_price),
                photo=subscription_img,
                reply_markup=choose_payment_options_kb(profile.language, "subscription"),
            )
        except TelegramBadRequest:
            await callback_query.message.answer(
                msg_text("image_error", profile.language),
                reply_markup=choose_payment_options_kb(profile.language, "subscription"),
            )
        await state.set_state(States.payment_choice)
    else:
        if subscription.exercises:
            await state.update_data(exercises=subscription.exercises, subscription=True)
            await show_subscription_page(callback_query, state, subscription)

    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


async def show_my_program_menu(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    if program := await Cache.workout.get_program(profile.id):
        if await Cache.workout.check_payment_status(profile.id, "program"):
            await callback_query.answer(msg_text("program_not_ready", profile.language), show_alert=True)
            return

        else:
            await callback_query.message.answer(
                msg_text("select_action", profile.language), reply_markup=program_action_kb(profile.language)
            )
            await state.update_data(program=program.to_dict())
            await state.set_state(States.program_action_choice)
    else:
        await show_program_promo_page(callback_query, profile, state)
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


async def show_program_promo_page(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    program_img = Settings.BOT_PAYMENT_OPTIONS + f"program_{profile.language}.jpeg"
    client_profile = await Cache.client.get_client(profile.id)
    coach = await Cache.coach.get_coach(client_profile.assigned_to.pop())
    try:
        await callback_query.message.answer_photo(
            caption=msg_text("program_price", profile.language).format(price=coach.program_price),
            photo=program_img,
            reply_markup=choose_payment_options_kb(profile.language, "program"),
        )
    except TelegramBadRequest:
        await callback_query.message.answer(
            msg_text("image_error", profile.language),
            reply_markup=choose_payment_options_kb(profile.language, "program"),
        )
    await state.set_state(States.payment_choice)


async def show_exercises_menu(callback_query: CallbackQuery, state: FSMContext, profile: Profile) -> None:
    data = await state.get_data()
    exercises = data.get("exercises", {})
    days = data.get("days", [])
    program = await format_program(exercises, day=0)
    week_day = get_translated_week_day(profile.language, days[0]).lower()

    await callback_query.message.answer(
        msg_text("program_page", profile.language).format(program=program, day=week_day),
        reply_markup=program_view_kb(profile.language),
        disable_web_page_preview=True,
    )

    await state.update_data(client=True, day_index=0)
    await state.set_state(States.program_view)
    await callback_query.message.delete()


async def manage_subscription(callback_query: CallbackQuery, lang: str, client_id: str, state: FSMContext) -> None:
    await state.clear()
    subscription = await Cache.workout.get_subscription(int(client_id))

    if not subscription or not subscription.enabled:
        await callback_query.answer(msg_text("payment_required", lang), show_alert=True)
        await state.set_state(States.show_clients)
        return

    await callback_query.answer()
    days = subscription.workout_days
    week_day = get_translated_week_day(lang, days[0]).lower()

    if not subscription.exercises:
        await callback_query.message.answer(msg_text("no_program", lang))
        workouts_per_week = len(subscription.workout_days)
        await callback_query.message.answer(msg_text("workouts_per_week", lang).format(days=workouts_per_week))
        await callback_query.message.answer(msg_text("program_guide", lang))
        day_1_msg = await callback_query.message.answer(
            msg_text("enter_daily_program", lang).format(day=week_day),
            reply_markup=program_manage_kb(lang, workouts_per_week),
        )
        await state.update_data(
            chat_id=callback_query.message.chat.id,
            message_ids=[day_1_msg.message_id],
            split=workouts_per_week,
            days=days,
            day_index=0,
            exercises={},
            client_id=client_id,
            subscription=True,
        )
        await state.set_state(States.program_manage)

    else:
        program_text = await format_program(subscription.exercises, 0)
        await callback_query.message.answer(
            msg_text("program_page", lang).format(program=program_text, day=week_day),
            reply_markup=subscription_manage_kb(lang),
            disable_web_page_preview=True,
        )
        await state.update_data(
            exercises=subscription.exercises,
            days=days,
            client_id=client_id,
            day_index=0,
            subscription=True,
        )
        await state.set_state(States.subscription_manage)

    with suppress(TelegramBadRequest):
        await callback_query.message.delete()
