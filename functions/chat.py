import os
from contextlib import suppress
from typing import Any

import aiohttp
import loguru
from aiogram import F, Router, Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.keyboards import *
from bot.keyboards import new_coach_request
from bot.states import States
from common.cache_manager import cache_manager
from common.file_manager import avatar_manager
from functions.exercises import edit_subscription_exercises
from functions.menus import show_exercises_menu, show_main_menu, manage_subscription
from functions.profiles import get_or_load_profile
from functions.text_utils import format_new_client_message, get_client_page, get_workout_types
from common.models import Coach, Profile, Client
from functions.utils import program_menu_pagination
from services.profile_service import profile_service
from bot.texts.resources import MessageText
from bot.texts.text_manager import translate

logger = loguru.logger
bot = Bot(os.environ.get("BOT_TOKEN"))
BACKEND_URL = os.environ.get("BACKEND_URL")
OWNER_ID = os.environ.get("OWNER_ID")
message_router = Router()


async def send_message(
    recipient: Client | Coach,
    text: str,
    state: FSMContext = None,
    reply_markup=None,
    include_incoming_message: bool = True,
    photo=None,
    video=None,
) -> None:
    if state:
        data = await state.get_data()
        language = data.get("recipient_language", "ua")
        sender_name = data.get("sender_name", "")
    else:
        language = "ua"
        sender_name = ""

    recipient_data = await profile_service.get_profile(recipient.id)
    assert recipient_data

    if include_incoming_message:
        formatted_text = translate(MessageText.incoming_message, language).format(name=sender_name, message=text)
    else:
        formatted_text = text

    async with aiohttp.ClientSession():
        if video:
            await bot.send_video(
                chat_id=recipient_data.get("current_tg_id"),
                video=video.file_id,
                caption=formatted_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        elif photo:
            await bot.send_photo(
                chat_id=recipient_data.get("current_tg_id"),
                photo=photo.file_id,
                caption=formatted_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        else:
            await bot.send_message(
                chat_id=recipient_data.get("current_tg_id"),
                text=formatted_text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=ParseMode.HTML,
            )


async def notify_about_new_coach(tg_id: int, profile: Profile, data: dict[str, Any]) -> None:
    name = data.get("name")
    surname = data.get("surname")
    experience = data.get("work_experience")
    info = data.get("additional_info")
    card = data.get("payment_details")
    subscription_price = data.get("subscription_price")
    program_price = data.get("program_price")
    user = await bot.get_chat(tg_id)
    contact = f"@{user.username}" if user.username else tg_id

    file_name = data.get("profile_photo")
    photo = f"https://storage.googleapis.com/{avatar_manager.bucket_name}/{file_name}"
    async with aiohttp.ClientSession():
        await bot.send_photo(
            OWNER_ID,
            photo,
            caption=translate(MessageText.new_coach_request, "ru").format(
                name=name,
                surname=surname,
                experience=experience,
                info=info,
                card=card,
                subscription_price=subscription_price,
                program_price=program_price,
                contact=contact,
                profile_id=profile.id,
            ),
            reply_markup=new_coach_request(profile.id),
        )


@message_router.callback_query(F.data == "quit")
@message_router.callback_query(F.data == "later")
async def close_notification(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.message.delete()
    profile = await get_or_load_profile(callback_query.from_user.id)
    await show_main_menu(callback_query.message, profile, state)


@message_router.callback_query(F.data == "subscription_view")
async def subscription_view(callback_query: CallbackQuery, state: FSMContext):
    profile = await get_or_load_profile(callback_query.from_user.id)
    subscription_data = cache_manager.get_subscription(profile.id)
    await state.update_data(
        exercises=subscription_data.exercises,
        split=len(subscription_data.workout_days),
        days=subscription_data.workout_days,
        subscription=True,
    )
    await show_exercises_menu(callback_query, state, profile)


@message_router.callback_query(F.data.startswith("answer"))
async def answer_message(callback_query: CallbackQuery, state: FSMContext):
    profile = await get_or_load_profile(callback_query.from_user.id)
    recipient_id = int(callback_query.data.split("_")[1])
    if profile.status == "client":
        sender = cache_manager.get_client_by_id(profile.id)
        state_to_set = States.contact_coach
    else:
        sender = cache_manager.get_coach_by_id(profile.id)
        state_to_set = States.contact_client
        client = cache_manager.get_client_by_id(recipient_id)
        if client.status == "waiting_for_text":
            cache_manager.set_client_data(recipient_id, {"status": "default"})

    await callback_query.message.answer(translate(MessageText.enter_your_message, profile.language))
    await state.clear()
    await state.update_data(recipient_id=recipient_id, sender_name=sender.name)
    await state.set_state(state_to_set)


@message_router.callback_query(F.data == "previous")
@message_router.callback_query(F.data == "next")
async def navigate_days(callback_query: CallbackQuery, state: FSMContext):
    profile = await get_or_load_profile(callback_query.from_user.id)
    program = cache_manager.get_program(profile.id)
    data = await state.get_data()
    if data.get("subscription"):
        subscription = cache_manager.get_subscription(profile.id)
        split_number = len(subscription.workout_days)
        exercises = subscription.exercises
    else:
        split_number = program.split_number
        exercises = program.exercises_by_day
    await state.update_data(exercises=exercises, split=split_number, client=True)
    await program_menu_pagination(state, callback_query)


@message_router.callback_query(F.data.startswith("edit_"))
async def edit_subscription(callback_query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    day_index = data.get("day_index", 0)
    await edit_subscription_exercises(callback_query, state, day_index)


@message_router.callback_query(F.data.startswith("create"))
async def create_workouts(callback_query: CallbackQuery, state: FSMContext):
    profile = await get_or_load_profile(callback_query.from_user.id)
    await state.clear()
    parts = callback_query.data.split("_")
    service = parts[1]
    client_id = parts[2]
    await state.update_data(client_id=client_id)
    if service == "subscription":
        await manage_subscription(callback_query, profile.language, client_id, state)
    else:
        await callback_query.message.answer(translate(MessageText.workouts_number, profile.language))
        await state.set_state(States.workouts_number)
        with suppress(TelegramBadRequest):
            await callback_query.message.delete()


@message_router.callback_query(F.data.startswith("approve"))
async def approve_coach(callback_query: CallbackQuery, state: FSMContext):
    profile_id = callback_query.data.split("_")[1]
    await profile_service.edit_coach_profile(int(profile_id), dict(verified=True))
    cache_manager.set_coach_data(int(profile_id), {"verified": True})
    await callback_query.answer("👍")
    coach = cache_manager.get_coach_by_id(int(profile_id))
    if profile_data := await profile_service.get_profile(int(profile_id)):
        lang = profile_data.get("language")
    else:
        lang = "ua"
    await send_message(coach, translate(MessageText.coach_verified, lang=lang), state, include_incoming_message=False)
    await callback_query.message.delete()
    logger.info(f"Coach verification for profile_id {profile_id} approved")


@message_router.callback_query(F.data.startswith("decline"))
async def decline_coach(callback_query: CallbackQuery, state: FSMContext):
    profile_id = callback_query.data.split("_")[1]
    await callback_query.answer("👎")
    coach = cache_manager.get_coach_by_id(profile_id)
    if profile_data := await profile_service.get_profile(int(profile_id)):
        lang = profile_data.get("language")
    else:
        lang = "ua"
    await send_message(coach, translate(MessageText.coach_declined, lang=lang), state, include_incoming_message=False)
    await callback_query.message.delete()
    logger.info(f"Coach verification for profile_id {profile_id} declined")


async def contact_client(callback_query: CallbackQuery, profile: Profile, client_id: str, state: FSMContext) -> None:
    await callback_query.answer()
    await callback_query.message.answer(translate(MessageText.enter_your_message, profile.language))
    await callback_query.message.delete()
    coach = cache_manager.get_coach_by_id(profile.id)
    await state.clear()
    await state.update_data(recipient_id=client_id, sender_name=coach.name)
    await state.set_state(States.contact_client)


async def client_request(coach: Coach, client: Client, data: dict[str, Any]) -> None:
    coach_data = await profile_service.get_profile(coach.id)
    coach_lang = cache_manager.get_profile_info_by_key(coach_data.get("current_tg_id"), coach.id, "language")
    data["recipient_language"] = coach_lang
    service = data.get("request_type")
    preferable_workout_type = data.get("workout_type")
    client_data = await profile_service.get_profile(client.id)
    client_lang = cache_manager.get_profile_info_by_key(client_data.get("current_tg_id"), client.id, "language")
    workout_types = await get_workout_types(coach_lang)
    preferable_workouts_type = workout_types.get(preferable_workout_type, "unknown")
    subscription = cache_manager.get_subscription(client.id)
    client_page = await get_client_page(client, coach_lang, subscription, data)
    text = await format_new_client_message(data, coach_lang, client_lang, preferable_workouts_type)
    reply_markup = (
        new_incoming_request(coach_lang, client.id)
        if data.get("new_client")
        else incoming_request(coach_lang, service, client.id)
    )

    await send_message(
        recipient=coach,
        text=text,
        state=None,
        include_incoming_message=False,
    )

    if data.get("wishes"):
        await send_message(
            recipient=coach,
            text=data.get("wishes"),
            state=None,
            include_incoming_message=False,
        )

    await send_message(
        recipient=coach,
        text=translate(MessageText.client_page, coach_lang).format(**client_page),
        state=None,
        reply_markup=reply_markup,
        include_incoming_message=False,
    )
