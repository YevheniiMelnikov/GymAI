import os
from contextlib import suppress
from datetime import datetime

import loguru
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto, Message
from dateutil.relativedelta import relativedelta

from bot.keyboards import *
from bot.keyboards import (choose_coach, program_manage_menu, program_view_kb,
                           select_service, subscription_manage_menu)
from common.backend_service import backend_service
from common.exceptions import UserServiceError
from common.file_manager import avatar_manager
from common.functions.profiles import get_or_load_profile
from common.functions.text_utils import *
from common.models import Client, Coach, Profile, Subscription
from common.settings import BOT_PAYMENT_OPTIONS
from texts.resources import MessageText
from texts.text_manager import translate

logger = loguru.logger
bot = Bot(os.environ.get("BOT_TOKEN"))


async def show_subscription_page(callback_query: CallbackQuery, state: FSMContext, subscription: Subscription) -> None:
    await callback_query.answer()
    profile = await get_or_load_profile(callback_query.from_user.id)
    payment_date = datetime.strptime(subscription.payment_date, "%Y-%m-%d")
    next_payment_date = payment_date + relativedelta(months=1)
    next_payment_date_str = next_payment_date.strftime("%Y-%m-%d")
    enabled_status = "✅" if subscription.enabled else "❌"
    await state.set_state(States.show_subscription)
    await callback_query.message.answer(
        translate(MessageText.subscription_page, profile.language).format(
            next_payment_date=next_payment_date_str, enabled=enabled_status, price=subscription.price
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
            questionnaire = cache_manager.get_client_by_id(profile.id)
        except UserServiceError:
            questionnaire = None
        reply_markup = edit_client_profile(profile.language) if questionnaire else None
        await state.update_data(role="client")

    else:
        try:
            questionnaire = cache_manager.get_coach_by_id(profile.id)
        except UserServiceError:
            questionnaire = None
        reply_markup = edit_coach_profile(profile.language) if questionnaire else None
        await state.update_data(role="coach")

    state_to_set = States.edit_profile if questionnaire else States.name
    response_message = MessageText.choose_profile_parameter if questionnaire else MessageText.edit_profile
    profile_msg = await message.answer(
        text=translate(response_message, lang=profile.language), reply_markup=reply_markup
    )
    with suppress(TelegramBadRequest):
        await message.delete()
    await state.update_data(message_ids=[profile_msg.message_id], chat_id=message.chat.id)
    await state.set_state(state_to_set)

    if not questionnaire:
        name_msg = await message.answer(translate(MessageText.name, lang=profile.language))
        await state.update_data(message_ids=[profile_msg.message_id, name_msg.message_id])


async def show_main_menu(message: Message, profile: Profile, state: FSMContext) -> None:
    menu = client_menu_keyboard if profile.status == "client" else coach_menu_keyboard
    await state.clear()
    await state.update_data(profile=Profile.to_dict(profile))
    await state.set_state(States.main_menu)
    await message.answer(
        text=translate(MessageText.main_menu, lang=profile.language), reply_markup=menu(profile.language)
    )
    with suppress(TelegramBadRequest):
        await message.delete()


async def show_clients(message: Message, clients: list[Client], state: FSMContext, current_index=0) -> None:
    profile = await get_or_load_profile(message.chat.id)
    current_index %= len(clients)
    current_client = clients[current_index]
    subscription = True if cache_manager.get_subscription(current_client.id) else False
    data = await state.get_data()
    client_info = await get_client_page(current_client, profile.language, subscription, data)
    client_data = [Client.to_dict(client) for client in clients]

    await state.update_data(clients=client_data)
    await message.edit_text(
        text=translate(MessageText.client_page, profile.language).format(**client_info),
        reply_markup=client_select_menu(profile.language, current_client.id, current_index),
        parse_mode="HTML",
    )
    await state.set_state(States.show_clients)


async def show_coaches_menu(message: Message, coaches: list[Coach], current_index=0) -> None:
    profile = await get_or_load_profile(message.chat.id)
    current_index %= len(coaches)
    current_coach = coaches[current_index]
    coach_info = get_coach_page(current_coach)
    text = translate(MessageText.coach_page, profile.language)
    coach_photo_url = f"https://storage.googleapis.com/{avatar_manager.bucket_name}/{current_coach.profile_photo}"
    formatted_text = text.format(**coach_info)

    try:
        media = InputMediaPhoto(media=coach_photo_url)
        if message.photo:
            await message.edit_media(media=media)
            await message.edit_caption(
                caption=formatted_text,
                reply_markup=coach_select_menu(profile.language, current_coach.id, current_index),
                parse_mode=ParseMode.HTML,
            )
        else:
            await bot.send_photo(
                message.chat.id,
                photo=coach_photo_url,
                caption=formatted_text,
                reply_markup=coach_select_menu(profile.language, current_coach.id, current_index),
                parse_mode=ParseMode.HTML,
            )
    except TelegramBadRequest:
        await message.answer(
            text=formatted_text,
            reply_markup=coach_select_menu(profile.language, current_coach.id, current_index),
            parse_mode=ParseMode.HTML,
        )
        with suppress(TelegramBadRequest):
            await message.delete()


async def show_my_profile_menu(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    await callback_query.answer()
    try:
        user = (
            cache_manager.get_client_by_id(profile.id)
            if profile.status == "client"
            else cache_manager.get_coach_by_id(profile.id)
        )
    except UserServiceError:
        user_data = await backend_service.get_profile(profile.id)
        if user_data:
            if profile.status == "client":
                user = Client.from_dict(user_data)
                cache_manager.set_client_data(profile.id, user_data)
            else:
                user = Coach.from_dict(user_data)
                cache_manager.set_coach_data(profile.id, user_data)
        else:
            await show_profile_editing_menu(callback_query.message, profile, state)
            return

    format_attributes = get_profile_attributes(role=profile.status, user=user, lang_code=profile.language)
    text = translate(
        MessageText.client_profile if profile.status == "client" else MessageText.coach_profile,
        lang=profile.language,
    ).format(**format_attributes)

    if profile.status == "coach" and getattr(user, "profile_photo", None):
        photo = f"https://storage.googleapis.com/{avatar_manager.bucket_name}/{user.profile_photo}"
        try:
            await callback_query.message.answer_photo(photo, text, reply_markup=profile_menu_keyboard(profile.language))
        except TelegramBadRequest:
            logger.error(f"Profile image of profile_id {profile.id} not found")
            await callback_query.message.answer(text, reply_markup=profile_menu_keyboard(profile.language))
    else:
        await callback_query.message.answer(text, reply_markup=profile_menu_keyboard(profile.language))

    await state.set_state(States.profile)
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


async def my_clients_menu(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    try:
        coach = cache_manager.get_coach_by_id(profile.id)
        assigned_ids = coach.assigned_to if coach.assigned_to else None
    except UserServiceError:
        await callback_query.answer(translate(MessageText.coach_info_message, lang=profile.language), show_alert=True)
        return

    if assigned_ids:
        await callback_query.answer()
        try:
            clients = [cache_manager.get_client_by_id(client) for client in assigned_ids]
        except UserServiceError:
            clients = []
            for profile_id in assigned_ids:
                if profile_data := await backend_service.get_profile(profile_id):
                    clients.append(Client.from_dict(profile_data))
        await show_clients(callback_query.message, clients, state)
    else:
        if not coach.verified:
            await callback_query.answer(
                text=translate(MessageText.coach_info_message, profile.language), show_alert=True
            )
        await callback_query.answer(translate(MessageText.no_clients, profile.language), show_alert=True)
        await state.set_state(States.main_menu)
        return


async def show_my_workouts_menu(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    try:
        client = cache_manager.get_client_by_id(profile.id)
    except UserServiceError:
        await callback_query.answer(
            translate(MessageText.questionnaire_not_completed, profile.language), show_alert=True
        )
        await show_profile_editing_menu(callback_query.message, profile, state)
        return

    if not client.assigned_to:
        await callback_query.message.answer(
            text=translate(MessageText.no_program, lang=profile.language),
            reply_markup=choose_coach(profile.language),
        )
        await state.set_state(States.choose_coach)
    else:
        await state.set_state(States.select_service)
        await callback_query.message.answer(
            text=translate(MessageText.select_service, lang=profile.language),
            reply_markup=select_service(profile.language),
        )

    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


async def show_my_subscription_menu(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    subscription = cache_manager.get_subscription(profile.id)
    if not subscription or not subscription.enabled:
        subscription_img = BOT_PAYMENT_OPTIONS + f"subscription_{profile.language}.jpeg"
        try:
            await callback_query.message.answer_photo(
                photo=subscription_img,
                reply_markup=choose_payment_options(profile.language, "subscription"),
            )
        except TelegramBadRequest:
            await callback_query.message.answer(
                translate(MessageText.image_error, profile.language),
                reply_markup=choose_payment_options(profile.language, "subscription"),
            )
        await state.set_state(States.payment_choice)
    else:
        if exercises := subscription.exercises:
            await state.update_data(exercises=exercises, subscription=True)
            await show_subscription_page(callback_query, state, subscription)
        else:
            await callback_query.answer(translate(MessageText.program_not_ready, profile.language), show_alert=True)
            return

    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


async def show_my_program_menu(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    if program := cache_manager.get_program(profile.id):
        program_paid = cache_manager.check_payment_status(profile.id, "program")
        if program_paid:
            await callback_query.answer(translate(MessageText.program_not_ready, profile.language), show_alert=True)
            return
        else:
            program_text = await format_program(program.exercises_by_day, 0)
            await callback_query.message.answer(
                text=translate(MessageText.program_page, lang=profile.language).format(program=program_text, day=1),
                reply_markup=program_view_kb(profile.language),
                disable_web_page_preview=True,
            )
            with suppress(TelegramBadRequest):
                await callback_query.message.delete()
            await state.update_data(exercises=program.exercises_by_day, split=program.split_number, client=True)
            await state.set_state(States.program_view)
    else:
        program_img = BOT_PAYMENT_OPTIONS + f"program_{profile.language}.jpeg"
        try:
            await callback_query.message.answer_photo(
                photo=program_img,
                reply_markup=choose_payment_options(profile.language, "program"),
            )
        except TelegramBadRequest:
            await callback_query.message.answer(
                translate(MessageText.image_error, profile.language),
                reply_markup=choose_payment_options(profile.language, "program"),
            )
        await state.set_state(States.payment_choice)
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


async def show_exercises_menu(callback_query: CallbackQuery, state: FSMContext, profile: Profile) -> None:
    data = await state.get_data()
    exercises = data.get("exercises", {})
    program = await format_program(exercises, day=0)
    days = data.get("days", [])
    week_day = get_translated_week_day(profile.language, days[0]).lower()

    await callback_query.message.answer(
        text=translate(MessageText.program_page, lang=profile.language).format(program=program, day=week_day),
        reply_markup=program_view_kb(profile.language),
        disable_web_page_preview=True,
    )

    await state.update_data(client=True, day_index=0)
    await state.set_state(States.program_view)
    await callback_query.message.delete()


async def show_manage_subscription_menu(
    callback_query: CallbackQuery, lang: str, client_id: str, state: FSMContext
) -> None:
    await state.clear()
    subscription = cache_manager.get_subscription(client_id)

    if not subscription or not subscription.enabled:
        await callback_query.answer(translate(MessageText.payment_required, lang))
        return

    await callback_query.answer()
    days = subscription.workout_days
    week_day = get_translated_week_day(lang, days[0]).lower()

    if not subscription.exercises:
        await callback_query.message.answer(translate(MessageText.no_program, lang))
        workouts_per_week = len(subscription.workout_days)
        await callback_query.message.answer(
            translate(MessageText.workouts_per_week, lang).format(days=workouts_per_week)
        )
        await callback_query.message.answer(text=translate(MessageText.program_guide, lang))
        day_1_msg = await callback_query.message.answer(
            translate(MessageText.enter_daily_program, lang).format(day=week_day),
            reply_markup=program_manage_menu(lang),
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
        program_text = await format_program({days[0]: subscription.exercises["0"]}, days[0])
        await callback_query.message.answer(
            text=translate(MessageText.program_page, lang).format(program=program_text, day=week_day),
            reply_markup=subscription_manage_menu(lang),
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
