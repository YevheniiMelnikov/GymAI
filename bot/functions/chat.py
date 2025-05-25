from typing import Any

import aiohttp
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import *
from bot.keyboards import new_coach_kb
from bot.singleton import bot
from bot.states import States
from bot.texts.text_manager import msg_text
from config.env_settings import Settings
from core.cache import Cache
from core.models import Coach, Profile, Client
from core.services import APIService
from core.services.outer.gstorage_service import avatar_manager
from bot.functions.text_utils import format_new_client_message, get_client_page, get_workout_types


async def send_message(
    recipient: Client | Coach,
    text: str,
    state: FSMContext | None = None,
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
        language = Settings.BOT_LANG
        sender_name = ""

    recipient_profile = await APIService.profile.get_profile(recipient.id)
    assert recipient_profile

    if include_incoming_message:
        formatted_text = msg_text("incoming_message", language).format(name=sender_name, message=text)
    else:
        formatted_text = text

    async with aiohttp.ClientSession():
        if video:
            await bot.send_video(
                chat_id=recipient_profile.tg_id,
                video=video.file_id,
                caption=formatted_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        elif photo:
            await bot.send_photo(
                chat_id=recipient_profile.tg_id,
                photo=photo.file_id,
                caption=formatted_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        else:
            await bot.send_message(
                chat_id=recipient_profile.tg_id,
                text=formatted_text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=ParseMode.HTML,
            )


async def send_coach_request(tg_id: int, profile: Profile, data: dict[str, Any]) -> None:
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
            chat_id=Settings.ADMIN_ID,
            photo=photo,
            caption=msg_text("new_coach_request", Settings.ADMIN_LANG).format(
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
            reply_markup=new_coach_kb(profile.id),
        )


async def contact_client(callback_query: CallbackQuery, profile: Profile, client_id: str, state: FSMContext) -> None:
    await callback_query.answer()
    await callback_query.message.answer(msg_text("enter_your_message", profile.language))
    await callback_query.message.delete()
    coach = await Cache.coach.get_coach(profile.id)
    await state.clear()
    await state.update_data(recipient_id=client_id, sender_name=coach.name)
    await state.set_state(States.contact_client)


async def client_request(coach: Coach, client: Client, data: dict[str, Any]) -> None:
    coach_profile = await APIService.profile.get_profile(coach.id)
    coach_lang = coach_profile.language
    data["recipient_language"] = coach_lang
    service = data.get("request_type")
    preferable_workout_type = data.get("workout_type")
    client_profile = await APIService.profile.get_profile(client.id)
    workout_types = await get_workout_types(coach_lang)
    preferable_workouts_type = workout_types.get(preferable_workout_type, "unknown")
    subscription = await Cache.workout.get_subscription(client.id)
    client_page = await get_client_page(client, coach_lang, subscription is not None, data)
    text = await format_new_client_message(data, coach_lang, client_profile.language, preferable_workouts_type)
    reply_markup = (
        client_msg_bk(coach_lang, client.id)
        if data.get("new_client")
        else incoming_request_kb(coach_lang, service, client.id)
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
        text=msg_text("client_page", coach_lang).format(**client_page),
        state=None,
        reply_markup=reply_markup,
        include_incoming_message=False,
    )


async def process_feedback_content(message: Message, profile: Profile) -> bool:
    if message.text:
        await bot.send_message(
            chat_id=Settings.ADMIN_ID,
            text=msg_text("new_feedback", Settings.ADMIN_LANG).format(profile_id=profile.id, feedback=message.text),
            parse_mode=ParseMode.HTML,
        )
        return True

    elif message.photo:
        await bot.send_message(
            chat_id=Settings.ADMIN_ID,
            text=msg_text("new_feedback", Settings.ADMIN_LANG).format(
                profile_id=profile.id, feedback=message.caption or ""
            ),
            parse_mode=ParseMode.HTML,
        )
        photo_id = message.photo[-1].file_id
        await bot.send_photo(
            chat_id=Settings.ADMIN_ID,
            photo=photo_id,
        )
        return True

    elif message.video:
        await bot.send_message(
            chat_id=Settings.ADMIN_ID,
            text=msg_text("new_feedback", Settings.ADMIN_LANG).format(
                profile_id=profile.id, feedback=message.caption or ""
            ),
            parse_mode=ParseMode.HTML,
        )
        await bot.send_video(
            chat_id=Settings.ADMIN_ID,
            video=message.video.file_id,
        )
        return True

    else:
        await message.answer(msg_text("invalid_content", profile.language))
        return False
