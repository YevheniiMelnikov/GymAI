import os
from contextlib import suppress
from dataclasses import asdict
from datetime import datetime
from typing import Any

import aiohttp
import loguru
from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, CallbackQuery, InputMediaPhoto, Message
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

from bot.keyboards import *
from bot.states import States
from common.exceptions import UserServiceError
from common.file_manager import avatar_manager, gif_manager
from common.models import Client, Coach, Exercise, Profile, Subscription
from common.user_service import user_service
from common.utils import *
from texts.exercises import exercise_dict
from texts.text_manager import MessageText, resource_manager, translate

logger = loguru.logger
load_dotenv()
bot = Bot(os.environ.get("BOT_TOKEN"))
BACKEND_URL = os.environ.get("BACKEND_URL")
OWNER_ID = os.environ.get("OWNER_ID")
sub_router = Router()


async def show_profile_editing_menu(message: Message, profile: Profile, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(lang=profile.language)

    if profile.status == "client":
        try:
            questionnaire = user_service.storage.get_client_by_id(profile.id)
        except UserServiceError:
            questionnaire = None
        reply_markup = edit_client_profile(profile.language) if questionnaire else None
        await state.update_data(role="client")

    else:
        try:
            questionnaire = user_service.storage.get_coach_by_id(profile.id)
        except UserServiceError:
            questionnaire = None
        reply_markup = edit_coach_profile(profile.language) if questionnaire else None
        await state.update_data(role="coach")

    state_to_set = States.edit_profile if questionnaire else States.name
    response_message = MessageText.choose_profile_parameter if questionnaire else MessageText.edit_profile
    await message.answer(text=translate(response_message, lang=profile.language), reply_markup=reply_markup)
    with suppress(TelegramBadRequest):
        await message.delete()
    await state.set_state(state_to_set)

    if not questionnaire:
        await message.answer(translate(MessageText.name, lang=profile.language))


async def show_main_menu(message: Message, profile: Profile, state: FSMContext) -> None:
    menu = client_menu_keyboard if profile.status == "client" else coach_menu_keyboard
    await state.clear()
    await state.set_state(States.main_menu)
    await state.update_data(profile=Profile.to_dict(profile))
    if profile.status == "coach":
        try:
            user_service.storage.get_coach_by_id(profile.id)
        except UserServiceError:
            await message.answer(translate(MessageText.coach_info_message, lang=profile.language))
    await message.answer(
        text=translate(MessageText.main_menu, lang=profile.language), reply_markup=menu(profile.language)
    )
    with suppress(TelegramBadRequest):
        await message.delete()


async def register_user(message: Message, state: FSMContext, data: dict) -> None:
    await state.update_data(email=message.text)
    if not await user_service.sign_up(
        username=data.get("username"),
        password=data.get("password"),
        email=message.text,
        status=data.get("account_type"),
        language=data.get("lang"),
    ):
        logger.error(f"Registration failed for user {message.from_user.id}")
        await handle_registration_failure(message, state, data.get("lang"))
        return

    logger.info(f"User {message.text} registered")
    token = await user_service.log_in(username=data.get("username"), password=data.get("password"))

    if not token:
        logger.error(f"Login failed for user {message.text} after registration")
        await handle_registration_failure(message, state, data.get("lang"))
        return

    logger.info(f"User {message.text} logged in")
    profile_data = await user_service.get_profile_by_username(data.get("username"))
    user_service.storage.set_profile(
        profile=profile_data,
        username=data.get("username"),
        auth_token=token,
        telegram_id=str(message.from_user.id),
        email=message.text,
    )
    await message.answer(text=translate(MessageText.registration_successful, lang=data.get("lang")))
    profile = user_service.storage.get_current_profile(message.from_user.id)
    await show_main_menu(message, profile, state)


async def handle_registration_failure(message: Message, state: FSMContext, lang: str) -> None:
    await message.answer(text=translate(MessageText.unexpected_error, lang=lang))
    await state.clear()
    await state.set_state(States.username)
    await message.answer(text=translate(MessageText.username, lang=lang))


async def sign_in(message: Message, state: FSMContext, data: dict) -> None:
    token = await user_service.log_in(username=data["username"], password=message.text)
    if not token:
        attempts = data.get("login_attempts", 0) + 1
        await state.update_data(login_attempts=attempts)
        if attempts >= 3:
            await message.answer(text=translate(MessageText.reset_password_offer, lang=data.get("lang")))
        else:
            await message.answer(text=translate(MessageText.invalid_credentials, lang=data.get("lang")))
            await state.set_state(States.username)
            await message.answer(text=translate(MessageText.username, lang=data.get("lang")))
        await message.delete()
        return

    logger.info(f"User {message.from_user.id} logged in")
    profile = await user_service.get_profile_by_username(data["username"])
    if not profile:
        await message.answer(text=translate(MessageText.unexpected_error, lang=data.get("lang")))
        await state.set_state(States.username)
        await message.answer(text=translate(MessageText.username, lang=data.get("lang")))
        await message.delete()
        return

    await state.update_data(login_attempts=0)
    user_service.storage.set_profile(
        profile=profile, username=data["username"], auth_token=token, telegram_id=str(message.from_user.id)
    )
    logger.info(f"profile_id {profile.id} set for user {message.from_user.id}")
    await message.answer(text=translate(MessageText.signed_in, lang=data.get("lang")))
    await show_main_menu(message, profile, state)
    with suppress(TelegramBadRequest):
        await message.delete()


async def set_bot_commands(lang: str = "ua") -> None:
    command_texts = resource_manager.commands
    commands = [BotCommand(command=cmd, description=desc[lang]) for cmd, desc in command_texts.items()]
    await bot.set_my_commands(commands)


async def update_user_info(message: Message, state: FSMContext, role: str) -> None:
    data = await state.get_data()
    data["tg_id"] = message.from_user.id
    try:
        profile = user_service.storage.get_current_profile(message.chat.id)
        if not profile:
            raise ValueError("Profile not found")

        if role == "client":
            user_service.storage.set_client_data(str(profile.id), data)
        else:
            if not data.get("edit_mode"):
                await message.answer(translate(MessageText.wait_for_verification, data.get("lang")))
                await notify_about_new_coach(message.from_user.id, profile, data)
            user_service.storage.set_coach_data(str(profile.id), data)

        token = user_service.storage.get_profile_info_by_key(message.chat.id, profile.id, "auth_token")
        if not token:
            raise ValueError("Authentication token not found")

        await user_service.edit_profile(profile.id, data, token)
        await message.answer(translate(MessageText.your_data_updated, lang=data.get("lang")))
        await state.clear()
        await state.update_data(profile=Profile.to_dict(profile))
        await state.set_state(States.main_menu)

        reply_markup = (
            client_menu_keyboard(data.get("lang")) if role == "client" else coach_menu_keyboard(data.get("lang"))
        )
        await message.answer(translate(MessageText.main_menu, lang=data.get("lang")), reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Unexpected error updating profile: {e}")
        await message.answer(translate(MessageText.unexpected_error, lang=data.get("lang")))
    finally:
        await message.delete()


async def notify_about_new_coach(tg_id: int, profile: Profile, data: dict[str, Any]) -> None:
    name = data.get("name")
    experience = data.get("work_experience")
    info = data.get("additional_info")
    payment = data.get("payment_details")
    file_name = data.get("profile_photo")
    photo = f"https://storage.googleapis.com/{avatar_manager.bucket_name}/{file_name}"
    user = await bot.get_chat(tg_id)
    contact = f"@{user.username}" if user.username else tg_id
    async with aiohttp.ClientSession():
        await bot.send_photo(
            OWNER_ID,
            photo,
            caption=translate(MessageText.new_coach_request, "ru").format(
                name=name, experience=experience, info=info, payment=payment, contact=contact, profile_id=profile.id
            ),
            reply_markup=new_coach_request(),
        )

    @sub_router.callback_query(F.data == "coach_approve")  # TODO: FIND BETTER SOLUTION
    async def approve_coach(callback_query: CallbackQuery):
        token = user_service.storage.get_profile_info_by_key(tg_id, profile.id, "auth_token")
        await user_service.edit_profile(profile.id, {"verified": True}, token)
        user_service.storage.set_coach_data(str(profile.id), {"verified": True})
        await callback_query.answer("👍")
        await bot.send_message(tg_id, translate(MessageText.coach_verified, lang=profile.language))
        logger.info(f"Coach verification for profile_id {profile.id} approved")

    @sub_router.callback_query(F.data == "coach_decline")
    async def decline_coach(callback_query: CallbackQuery):
        await callback_query.answer("👎")
        await bot.send_message(tg_id, translate(MessageText.coach_declined, lang=profile.language))
        logger.info(f"Coach verification for profile_id {profile.id} declined")


async def show_coaches(message: Message, coaches: list[Coach], current_index=0) -> None:
    profile = user_service.storage.get_current_profile(message.chat.id)
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


async def assign_coach(coach: Coach, client: Client) -> None:
    coach_clients = coach.assigned_to if isinstance(coach.assigned_to, list) else []
    if client.id not in coach_clients:
        coach_clients.append(int(client.id))
        user_service.storage.set_coach_data(str(coach.id), {"assigned_to": coach_clients})

    user_service.storage.set_client_data(str(client.id), {"assigned_to": [int(coach.id)]})
    token = user_service.storage.get_profile_info_by_key(client.tg_id, client.id, "auth_token")
    await user_service.edit_profile(client.id, {"assigned_to": [coach.id]}, token)
    await user_service.edit_profile(coach.id, {"assigned_to": coach_clients}, token)


async def handle_contact_action(
    callback_query: CallbackQuery, profile: Profile, client_id: str, state: FSMContext
) -> None:
    await callback_query.message.answer(translate(MessageText.enter_your_message, profile.language))
    await callback_query.message.delete()
    coach = user_service.storage.get_coach_by_id(profile.id)
    await state.clear()
    await state.update_data(recipient_id=client_id, sender_name=coach.name)
    await state.set_state(States.contact_client)


async def handle_program_action(
    callback_query: CallbackQuery, profile: Profile, client_id: str, state: FSMContext
) -> None:
    program_paid = user_service.storage.check_payment_status(client_id, "program")
    workout_data = user_service.storage.get_program(str(client_id))

    if not program_paid and not workout_data:
        await callback_query.answer(
            text=translate(MessageText.payment_required, lang=profile.language), show_alert=True
        )
        return

    if workout_data and workout_data.exercises_by_day:
        program = await format_program(workout_data.exercises_by_day, 0)
        del_msg = await callback_query.message.answer(
            text=translate(MessageText.program_page, lang=profile.language).format(program=program, day=1),
            reply_markup=program_edit_kb(profile.language),
            disable_web_page_preview=True,
        )
        await state.update_data(
            exercises=workout_data.exercises_by_day, del_msg=del_msg.message_id, client_id=client_id, day_index=0
        )
        await state.set_state(States.program_edit)
        await callback_query.message.delete()
        return

    else:
        del_msg = await callback_query.message.answer(text=translate(MessageText.no_program, lang=profile.language))

    await state.update_data(del_msg=del_msg.message_id, client_id=client_id)
    await callback_query.message.answer(translate(MessageText.workouts_number, profile.language))
    await state.set_state(States.workouts_number)
    await callback_query.message.delete()


async def handle_subscription_action(
    callback_query: CallbackQuery, profile: Profile, client_id: str, state: FSMContext
) -> None:
    subscription = user_service.storage.get_subscription(client_id)

    if not subscription or not subscription.enabled:
        await callback_query.answer(translate(MessageText.payment_required, profile.language))
        return

    days = subscription.workout_days

    if not subscription.exercises:
        await callback_query.message.answer(translate(MessageText.no_program, profile.language))
        workouts_per_week = len(subscription.workout_days)
        await callback_query.message.answer(
            translate(MessageText.workouts_per_week, lang=profile.language).format(days=workouts_per_week)
        )
        await callback_query.message.answer(text=translate(MessageText.program_guide, lang=profile.language))
        day_1_msg = await callback_query.message.answer(
            translate(MessageText.enter_daily_program, profile.language).format(day=1),
            reply_markup=program_manage_menu(profile.language),
        )
        await state.update_data(
            day_1_msg=day_1_msg.message_id,
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
        week_day = get_translated_week_day(profile.language, days[0])
        del_msg = await callback_query.message.answer(
            text=translate(MessageText.program_page, profile.language).format(program=program_text, day=week_day),
            reply_markup=subscription_manage_menu(profile.language),
            disable_web_page_preview=True,
        )
        await state.update_data(
            del_msg=del_msg.message_id,
            exercises=subscription.exercises,
            days=days,
            client_id=client_id,
            day_index=0,
            subscription=True,
        )
        await state.set_state(States.subscription_manage)

    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


async def handle_client_pagination(callback_query: CallbackQuery, profile, index: int, state: FSMContext) -> None:
    data = await state.get_data()
    clients = [Client.from_dict(data) for data in data["clients"]]

    if not clients:
        await callback_query.answer(translate(MessageText.no_clients, profile.language))
        return

    if index < 0 or index >= len(clients):
        await callback_query.answer(translate(MessageText.out_of_range, profile.language))
        return

    await show_clients(callback_query.message, clients, state, index)


async def handle_my_profile(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    try:
        user = (
            user_service.storage.get_client_by_id(profile.id)
            if profile.status == "client"
            else user_service.storage.get_coach_by_id(profile.id)
        )
    except UserServiceError:
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


async def handle_my_clients(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    try:
        coach = user_service.storage.get_coach_by_id(profile.id)
        assigned_ids = coach.assigned_to if coach.assigned_to else None
    except UserServiceError as e:
        logger.error(f"Could not get coach profile for {profile.id}: {e}")
        await callback_query.message.answer(translate(MessageText.unexpected_error, profile.language))
        return

    if assigned_ids:
        clients = [user_service.storage.get_client_by_id(client) for client in assigned_ids]
        await show_clients(callback_query.message, clients, state)
    else:
        if not coach.verified:
            await callback_query.answer(
                text=translate(MessageText.coach_info_message, profile.language), show_alert=True
            )
        await callback_query.message.answer(translate(MessageText.no_clients, profile.language))
        await state.set_state(States.main_menu)
        await show_main_menu(callback_query.message, profile, state)


async def handle_my_program(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    try:
        client = user_service.storage.get_client_by_id(profile.id)
    except UserServiceError:
        await callback_query.message.answer(translate(MessageText.questionnaire_not_completed, profile.language))
        await show_profile_editing_menu(callback_query.message, profile, state)
        return

    assigned = client.assigned_to if client.assigned_to else None
    if not assigned:
        await callback_query.message.answer(
            text=translate(MessageText.no_program, lang=profile.language),
            reply_markup=choose_coach(profile.language),
        )
        await state.set_state(States.choose_coach)
        return

    await state.set_state(States.select_service)
    await callback_query.message.answer(
        text=translate(MessageText.select_service, lang=profile.language),
        reply_markup=select_service(profile.language),
    )
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


async def show_clients(message: Message, clients: list[Client], state: FSMContext, current_index=0) -> None:
    profile = user_service.storage.get_current_profile(message.chat.id)
    current_index %= len(clients)
    current_client = clients[current_index]
    subscription = True if user_service.storage.get_subscription(current_client.id) else False
    waiting_program = user_service.storage.check_payment_status(current_client.id, "program")
    waiting_subscription = user_service.storage.check_payment_status(current_client.id, "subscription")
    status = True if waiting_program or waiting_subscription else False
    client_info = get_client_page(current_client, profile.language, subscription, status)
    client_data = [Client.to_dict(client) for client in clients]

    await state.update_data(clients=client_data)
    await message.edit_text(
        text=translate(MessageText.client_page, profile.language).format(**client_info),
        reply_markup=client_select_menu(profile.language, current_client.id, current_index),
        parse_mode="HTML",
    )
    await state.set_state(States.show_clients)


async def send_message(
    recipient: Client | Coach,
    text: str,
    state: FSMContext,
    reply_markup=None,
    include_incoming_message: bool = True,
    photo=None,
) -> None:
    data = await state.get_data()
    language = data.get("recipient_language", "ua")

    if include_incoming_message:
        formatted_text = translate(MessageText.incoming_message, language).format(
            name=data.get("sender_name", ""), message=text
        )
    else:
        formatted_text = text

    async with aiohttp.ClientSession():
        if photo:
            await bot.send_photo(
                chat_id=recipient.tg_id,
                photo=photo.file_id,
                caption=formatted_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        else:
            await bot.send_message(
                chat_id=recipient.tg_id,
                text=formatted_text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=ParseMode.HTML,
            )

    @sub_router.callback_query(F.data == "quit")
    @sub_router.callback_query(F.data == "later")
    async def close_notification(callback_query: CallbackQuery):
        await callback_query.message.delete()

    @sub_router.callback_query(F.data == "view")
    async def view_subscription(callback_query: CallbackQuery, state: FSMContext):
        profile = user_service.storage.get_current_profile(callback_query.from_user.id)
        subscription_data = user_service.storage.get_subscription(profile.id)
        await state.update_data(
            exercises=subscription_data.exercises,
            split=len(subscription_data.workout_days),
            days=subscription_data.workout_days,
        )
        await show_exercises(callback_query, state, profile)

    @sub_router.callback_query(F.data.startswith("answer"))
    async def answer_message(callback_query: CallbackQuery, state: FSMContext):
        profile = user_service.storage.get_current_profile(callback_query.from_user.id)
        sender = (
            user_service.storage.get_client_by_id(profile.id)
            if profile.status == "client"
            else user_service.storage.get_coach_by_id(profile.id)
        )
        await callback_query.message.answer(translate(MessageText.enter_your_message, profile.language))
        await state.clear()
        status_to_set = States.contact_coach if profile.status == "client" else States.contact_client
        recipient_id = int(callback_query.data.split("_")[1])
        await state.update_data(recipient_id=recipient_id, sender_name=sender.name)
        await state.set_state(status_to_set)

    @sub_router.callback_query(F.data == "prev_day")
    @sub_router.callback_query(F.data == "next_day")
    async def navigate_days(callback_query: CallbackQuery, state: FSMContext):
        profile = user_service.storage.get_current_profile(callback_query.from_user.id)
        program = user_service.storage.get_program(str(profile.id))

        if program:
            split_number = program.split_number
            exercises = program.exercises_by_day
        else:
            subscription = user_service.storage.get_subscription(str(profile.id))
            split_number = len(subscription.workout_days)
            exercises = subscription.exercises

        await state.update_data(exercises=exercises, split=split_number, client=True)
        await handle_program_pagination(state, callback_query)

    @sub_router.callback_query(F.data.startswith("edit_"))
    async def edit_program(callback_query: CallbackQuery, state: FSMContext):
        profile = user_service.storage.get_current_profile(callback_query.from_user.id)
        client_id = callback_query.data.split("_")[1]
        day = callback_query.data.split("_")[2]
        subscription = user_service.storage.get_subscription(client_id)
        program_text = await format_program(subscription.exercises, 0)
        exercises = subscription.exercises.get(day)
        await state.update_data(exercises=exercises, client_id=client_id, day=day, subscription=True)
        await state.set_state(States.program_edit)
        await callback_query.message.answer(
            text=translate(MessageText.program_page, profile.language).format(program=program_text, day=day),
            disable_web_page_preview=True,
            reply_markup=program_edit_kb(profile.language),
        )
        await callback_query.message.delete()

    @sub_router.callback_query(F.data.startswith("create"))
    async def create_workout_plan(callback_query: CallbackQuery, state: FSMContext):
        profile = user_service.storage.get_current_profile(callback_query.from_user.id)
        await state.clear()
        service = callback_query.data.split("_")[1]
        client_id = callback_query.data.split("_")[2]
        await state.update_data(client_id=client_id)
        if service == "subscription":
            await handle_subscription_action(callback_query, profile, client_id, state)
        else:
            await callback_query.message.answer(translate(MessageText.workouts_number, profile.language))
            await state.set_state(States.workouts_number)
            with suppress(TelegramBadRequest):
                await callback_query.message.delete()


async def format_program(exercises: dict[str, any], day: int) -> str:
    program_lines = []
    exercises_data = exercises.get(str(day), [])
    exercises = [Exercise(**e) if isinstance(e, dict) else e for e in exercises_data]

    for idx, exercise in enumerate(exercises):
        line = f"{idx + 1}. {exercise.name} | {exercise.sets} x {exercise.reps}"
        if exercise.weight:
            line += f" | {exercise.weight} kg"
        if exercise.gif_link:
            line += f" | <a href='{exercise.gif_link}'>GIF</a>"
        program_lines.append(line)

    return "\n".join(program_lines)


async def find_related_gif(exercise: str) -> str | None:
    try:
        exercise = exercise.lower()
        for filename, synonyms in exercise_dict.items():
            if exercise in (syn.lower() for syn in synonyms):
                cached_filename = user_service.storage.get_exercise_gif(exercise)
                if cached_filename:
                    return f"https://storage.googleapis.com/{gif_manager.bucket_name}/{cached_filename}"

                blobs = list(gif_manager.bucket.list_blobs(prefix=filename))
                if blobs:
                    matching_blob = blobs[0]
                    if matching_blob.exists():
                        file_url = f"https://storage.googleapis.com/{gif_manager.bucket_name}/{matching_blob.name}"
                        user_service.storage.cache_gif_filename(exercise, matching_blob.name)
                        return file_url

    except Exception as e:
        logger.error(f"Failed to find gif for exercise {exercise}: {e}")

    logger.info(f"No matching file found for exercise: {exercise}")
    return None


async def client_request(coach: Coach, client: Client, state: FSMContext) -> None:
    data = await state.get_data()
    coach_lang = user_service.storage.get_profile_info_by_key(coach.tg_id, coach.id, "language")
    client_lang = user_service.storage.get_profile_info_by_key(client.tg_id, client.id, "language")
    await state.update_data(recipient_language=coach_lang)

    workout_types = await get_workout_types(coach_lang)
    preferable_workout_type = data.get("workout_type")
    service = data.get("request_type")
    preferable_type = workout_types.get(preferable_workout_type, "unknown")
    subscription = user_service.storage.get_subscription(client.id)
    waiting_program = user_service.storage.check_payment_status(client.id, "program")
    waiting_subscription = user_service.storage.check_payment_status(client.id, "subscription")
    status = True if waiting_program or waiting_subscription else False
    client_data = get_client_page(client, coach_lang, subscription, status)
    text = await format_message(data, coach_lang, client_lang, preferable_type)
    reply_markup = (
        new_incoming_request(coach_lang, client.id)
        if data.get("new_client")
        else incoming_request(coach_lang, service, client.id)
    )

    await send_message(
        recipient=coach,
        text=text,
        state=state,
        include_incoming_message=False,
    )

    await send_message(
        recipient=coach,
        text=translate(MessageText.client_page, coach_lang).format(**client_data),
        state=state,
        reply_markup=reply_markup,
        include_incoming_message=False,
    )


async def show_subscription_page(callback_query: CallbackQuery, state: FSMContext, subscription: Subscription) -> None:
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    payment_date = datetime.fromtimestamp(subscription.payment_date)
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


async def save_exercise(state: FSMContext, exercise: Exercise, input_data: Message | CallbackQuery) -> None:
    data = await state.get_data()

    for msg_key in ["del_msg", "exercise_msg", "program_msg", "day_1_msg", "weight_msg"]:
        if del_msg := data.get(msg_key):
            with suppress(TelegramBadRequest):
                await input_data.bot.delete_message(
                    input_data.chat.id if isinstance(input_data, Message) else input_data.message.chat.id, del_msg
                )

    profile = user_service.storage.get_current_profile(input_data.from_user.id)
    day_index = data.get("day_index", 0)
    exercises = data.get("exercises", {})

    if data.get("subscription"):
        days = data.get("days")
        current_day = days[day_index]
        day = get_translated_week_day(profile.language, current_day)
        if current_day not in exercises:
            exercises[day_index] = [asdict(exercise)]
        else:
            exercises[day_index].append(asdict(exercise))
        program = await format_program({days[day_index]: exercises[day_index]}, days[day_index])
    else:
        day = day_index + 1
        if day_index not in exercises:
            exercises[day_index] = [asdict(exercise)]
        else:
            exercises[day_index].append(asdict(exercise))
        program = await format_program({str(day_index): exercises[day_index]}, day_index)

    exercise_msg = await (input_data.answer if isinstance(input_data, Message) else input_data.message.answer)(
        translate(MessageText.enter_exercise, profile.language)
    )
    program_msg = await exercise_msg.answer(
        text=translate(MessageText.program_page, profile.language).format(program=program, day=day),
        reply_markup=program_manage_menu(profile.language),
        disable_web_page_preview=True,
    )

    await state.update_data(
        exercise_msg=exercise_msg.message_id,
        program_msg=program_msg.message_id,
        exercises=exercises,
        day_index=day_index + 1,
    )
    await state.set_state(States.program_manage)


async def handle_program_pagination(state: FSMContext, callback_query: CallbackQuery) -> None:
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)

    if callback_query.data == "quit":
        await handle_my_clients(callback_query, profile, state)
        return

    data = await state.get_data()
    current_day = data.get("day_index", 0)
    exercises = data.get("exercises", {})
    split_number = data.get("split")

    if callback_query.data == "prev_day":
        current_day -= 1
    else:
        current_day += 1

    if current_day < 0 or current_day >= split_number:
        await callback_query.answer(translate(MessageText.out_of_range, profile.language))
        current_day = max(0, min(current_day, split_number - 1))

    await state.update_data(day_index=current_day)
    program_text = await format_program(exercises, current_day)

    if data.get("client"):
        reply_markup = program_view_kb(profile.language)
        state_to_set = States.program_view
    else:
        reply_markup = program_edit_kb(profile.language)
        state_to_set = States.program_edit

    with suppress(TelegramBadRequest):
        await callback_query.message.edit_text(
            text=translate(MessageText.program_page, profile.language).format(
                program=program_text, day=current_day + 1
            ),
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )

    await state.set_state(state_to_set)


async def show_exercises(callback_query: CallbackQuery, state: FSMContext, profile: Profile) -> None:
    data = await state.get_data()
    exercises = data.get("exercises", {})
    updated_exercises = {str(index): exercise for index, exercise in enumerate(exercises.values())}
    program = await format_program(updated_exercises, day=0)

    await callback_query.message.answer(
        text=translate(MessageText.program_page, lang=profile.language).format(program=program, day=1),
        reply_markup=program_view_kb(profile.language),
        disable_web_page_preview=True,
    )

    await state.update_data(client=True)
    await state.set_state(States.program_view)
    await callback_query.message.delete()
