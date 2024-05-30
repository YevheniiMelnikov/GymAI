import os
from contextlib import suppress
from typing import Any

import aiohttp
import loguru
from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, CallbackQuery, InputMediaPhoto, Message
from dotenv import load_dotenv

from bot.keyboards import *
from bot.states import States
from common.file_manager import gif_manager
from common.models import Client, Coach, Profile
from common.user_service import user_service
from common.utils import get_client_page, get_coach_page, short_url
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
        questionnaire = user_service.storage.get_client_by_id(profile.id)
        reply_markup = edit_client_profile(profile.language) if questionnaire else None
        await state.update_data(role="client")

    else:
        questionnaire = user_service.storage.get_coach_by_id(profile.id)
        reply_markup = edit_coach_profile(profile.language) if questionnaire else None
        await state.update_data(role="coach")

    state_to_set = States.edit_profile if questionnaire else States.name
    response_message = MessageText.choose_profile_parameter if questionnaire else MessageText.edit_profile
    await message.answer(text=translate(response_message, lang=profile.language), reply_markup=reply_markup)
    await state.set_state(state_to_set)

    if not questionnaire:
        await message.answer(translate(MessageText.name, lang=profile.language))
    with suppress(TelegramBadRequest):
        await message.delete()


async def show_main_menu(message: Message, profile: Profile, state: FSMContext) -> None:
    menu = client_menu_keyboard if profile.status == "client" else coach_menu_keyboard
    await state.clear()
    await state.set_state(States.main_menu)
    await state.update_data(profile=Profile.to_dict(profile))
    if profile.status == "coach":
        coach = user_service.storage.get_coach_by_id(profile.id)
        if not coach or not coach.verified:
            await message.answer(translate(MessageText.coach_info_message, lang=profile.language))
    await message.answer(
        text=translate(MessageText.main_menu, lang=profile.language), reply_markup=menu(profile.language)
    )
    with suppress(TelegramBadRequest):
        await message.delete()


async def register_user(message: Message, state: FSMContext, data: dict) -> None:
    await state.update_data(email=message.text)
    if not await user_service.sign_up(
        username=data["username"],
        password=data["password"],
        email=message.text,
        status=data["account_type"],
        language=data["lang"],
    ):
        logger.error(f"Registration failed for user {message.from_user.id}")
        await handle_registration_failure(message, state, data.get("lang"))
        return

    logger.info(f"User {message.text} registered")
    token = await user_service.log_in(username=data["username"], password=data["password"])

    if not token:
        logger.error(f"Login failed for user {message.text} after registration")
        await handle_registration_failure(message, state, data.get("lang"))
        return

    logger.info(f"User {message.text} logged in")
    profile_data = await user_service.get_profile_by_username(data["username"])
    user_service.storage.set_profile(
        profile=profile_data,
        username=data["username"],
        auth_token=token,
        telegram_id=str(message.from_user.id),
        email=message.text,
    )
    await message.answer(text=translate(MessageText.registration_successful, lang=data.get("lang")))
    profile = user_service.storage.get_current_profile(message.from_user.id)
    await show_main_menu(message, profile, state)


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


async def handle_registration_failure(message: Message, state: FSMContext, lang: str) -> None:
    await message.answer(text=translate(MessageText.unexpected_error, lang=lang))
    await state.clear()
    await state.set_state(States.username)
    await message.answer(text=translate(MessageText.username, lang=lang))


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
    photo = f"https://storage.googleapis.com/coach_avatars/{file_name}"
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
        await callback_query.answer("Подтверждено")
        await bot.send_message(tg_id, translate(MessageText.coach_verified, lang=profile.language))
        logger.info(f"Coach verification for profile_id {profile.id} approved")

    @sub_router.callback_query(F.data == "coach_decline")
    async def decline_coach(callback_query: CallbackQuery):
        await callback_query.answer("Отклонено")
        await bot.send_message(tg_id, translate(MessageText.coach_declined, lang=profile.language))
        logger.info(f"Coach verification for profile_id {profile.id} declined")


async def show_coaches(message: Message, coaches: list[Coach], current_index=0) -> None:
    profile = user_service.storage.get_current_profile(message.chat.id)
    current_index %= len(coaches)
    current_coach = coaches[current_index]
    coach_info = get_coach_page(current_coach)
    text = translate(MessageText.coach_page, profile.language)
    coach_photo_url = f"https://storage.googleapis.com/coach_avatars/{current_coach.profile_photo}"
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


async def show_clients(message: Message, clients: list[Client], state: FSMContext, current_index=0) -> None:
    profile = user_service.storage.get_current_profile(message.chat.id)
    current_index %= len(clients)
    current_client = clients[current_index]
    client_info = get_client_page(current_client, profile.language)
    client_info["language"] = user_service.storage.set_profile_info_by_key(
        current_client.tg_id, current_client.id, "language"
    )
    text = translate(MessageText.client_page, profile.language).format(**client_info)
    client_data = [Client.to_dict(client) for client in clients]
    await state.update_data(clients=client_data)
    await state.set_state(States.show_clients)

    await message.edit_text(
        text=text,
        reply_markup=client_select_menu(profile.language, current_client.id, current_index),
        parse_mode="HTML",
    )


async def send_message(
    recipient: Client | Coach,
    text: str,
    state: FSMContext,
    reply_markup=None,
    include_incoming_message: bool = True,
) -> None:
    data = await state.get_data()
    if not isinstance(recipient, (Client, Coach)):
        raise ValueError("Recipient is not a valid Client or Coach object")

    language = data.get("recipient_language", "ua")

    if include_incoming_message:
        formatted_text = translate(MessageText.incoming_message, language).format(
            name=data.get("sender_name", ""), message=text
        )
    else:
        formatted_text = text

    async with aiohttp.ClientSession():
        await bot.send_message(
            chat_id=recipient.tg_id,
            text=formatted_text,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
            parse_mode=ParseMode.HTML,
        )

    @sub_router.callback_query(F.data in ("quit", "later"))
    async def close_notification(callback_query: CallbackQuery):
        await callback_query.message.delete()
        profile = user_service.storage.get_current_profile(recipient.tg_id)
        await state.set_state(States.main_menu)
        await show_main_menu(callback_query.message, profile, state)

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


async def format_program(exercises: list[tuple]) -> str:
    program_lines = []
    for idx, exercise in enumerate(exercises):
        exercise_name = exercise[0]
        link = exercise[1] if len(exercise) > 1 else None
        if not link:
            link = await generate_gif_link(exercise_name)

        if link:
            shorted_link = await short_url(link)
            program_lines.append(f"{idx + 1}. {exercise_name} | <a href='{shorted_link}'>GIF</a>")
        else:
            program_lines.append(f"{idx + 1}. {exercise_name}")

    return "\n".join(program_lines)


async def generate_gif_link(exercise: str) -> str | None:
    try:
        filename = user_service.storage.get_exercise_gif(exercise)
        if filename:
            return f"https://storage.googleapis.com/{gif_manager.bucket_name}/{filename}"
    except Exception as e:
        logger.error(f"Failed to generate gif link for exercise {exercise}: {e}")
    return None


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


async def new_client_notification(coach: Coach, client: Client, state: FSMContext) -> None:
    data = await state.get_data()
    coach_lang = user_service.storage.get_profile_info_by_key(coach.tg_id, coach.id, "language")
    client_lang = user_service.storage.get_profile_info_by_key(client.tg_id, client.id, "language")
    await state.update_data(recipient_language=coach_lang)

    workout_types = {
        "home": translate(ButtonText.home_workout, coach_lang),
        "street": translate(ButtonText.street_workout, coach_lang),
        "gym": translate(ButtonText.gym_workout, coach_lang),
    }

    preferable_workout_type = data.get("workout_type")
    preferable_type = workout_types.get(preferable_workout_type, "unknown")
    client_data = get_client_page(client, coach_lang)
    client_data["language"] = client_lang

    await send_message(
        recipient=coach,
        text=translate(MessageText.new_client, coach_lang).format(lang=client_lang, workout_type=preferable_type),
        state=state,
        include_incoming_message=False,
    )

    await send_message(
        recipient=coach,
        text=translate(MessageText.client_page, coach_lang).format(**client_data),
        state=state,
        reply_markup=new_client(coach_lang, coach.id),
        include_incoming_message=False,
    )
