from __future__ import annotations

from typing import Any, cast

import aiohttp
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from dependency_injector.wiring import inject, Provide

from bot.texts import msg_text
from bot.utils.other import answer_msg
from bot.keyboards import new_coach_kb, incoming_request_kb, client_msg_bk, program_view_kb
from bot.states import States
from config.env_settings import settings
from core.cache import Cache
from core.containers import App
from core.schemas import Coach, Profile, Client
from core.services import APIService
from bot.utils.text import format_new_client_message, get_client_page, get_workout_types
from core.services.outer import avatar_manager


@inject
async def send_message(
    recipient: Client | Coach,
    text: str,
    state: FSMContext | None = None,
    reply_markup=None,
    include_incoming_message: bool = True,
    photo=None,
    video=None,
    bot: Bot = Provide[App.bot],
) -> None:
    if state:
        data = await state.get_data()
        language = cast(str, data.get("recipient_language", settings.DEFAULT_LANG))
        sender_name = cast(str, data.get("sender_name", ""))
    else:
        language = settings.DEFAULT_LANG
        sender_name = ""

    recipient_profile = await APIService.profile.get_profile(recipient.profile)
    if recipient_profile is None:
        from loguru import logger

        logger.error(f"Profile not found for recipient id {recipient.id} in send_message")
        return

    formatted_text = (
        msg_text("incoming_message", language).format(name=sender_name, message=text)
        if include_incoming_message
        else text
    )

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


@inject
async def send_coach_request(
    tg_id: int,
    profile: Profile,
    data: dict[str, Any],
    bot: Bot = Provide[App.bot],
) -> None:
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
            chat_id=settings.ADMIN_ID,
            photo=photo,
            caption=msg_text("new_coach_request", settings.ADMIN_LANG).format(
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
    message = cast(Message, callback_query.message)
    await callback_query.answer()
    await answer_msg(callback_query, msg_text("enter_your_message", profile.language))
    await message.delete()
    coach = await Cache.coach.get_coach(profile.id)
    assert coach is not None
    await state.clear()
    await state.update_data(recipient_id=client_id, sender_name=coach.name)
    await state.set_state(States.contact_client)


async def client_request(coach: Coach, client: Client, data: dict[str, Any]) -> None:
    coach_profile = await APIService.profile.get_profile(coach.profile)
    if coach_profile is None:
        from loguru import logger

        logger.error(f"Coach profile not found for id {coach.id} in client_request")
        return
    coach_lang = coach_profile.language
    data["recipient_language"] = coach_lang

    service = cast(str, data.get("service_type"))
    preferable_workout_type = cast(str, data.get("workout_type"))
    wishes = data.get("wishes")

    client_profile = await APIService.profile.get_profile(client.profile)
    if client_profile is None:
        from loguru import logger

        logger.error(f"Client profile not found for id {client.id} in client_request")
        return

    workout_types: dict[str, str] = get_workout_types(coach_lang)
    preferable_workouts_type = workout_types.get(preferable_workout_type, "unknown")
    subscription = await Cache.workout.get_latest_subscription(client.id)

    client_page = await get_client_page(client, coach_lang, subscription is not None, data)
    text = await format_new_client_message(data, coach_lang, client_profile.language, preferable_workouts_type)

    reply_markup = (
        client_msg_bk(coach_lang, client.id)
        if data.get("new_client")
        else incoming_request_kb(coach_lang, service, client.id)
    )

    await send_message(recipient=coach, text=text, state=None, include_incoming_message=False)

    if wishes:
        await send_message(recipient=coach, text=cast(str, wishes), state=None, include_incoming_message=False)

    await send_message(
        recipient=coach,
        text=msg_text("client_page", coach_lang).format(**client_page),
        state=None,
        reply_markup=reply_markup,
        include_incoming_message=False,
    )


@inject
async def process_feedback_content(
    message: Message,
    profile: Profile,
    bot: Bot = Provide[App.bot],
) -> bool:
    text = msg_text("new_feedback", settings.ADMIN_LANG).format(
        profile_id=profile.id,
        feedback=message.text or message.caption or "",
    )

    if message.text:
        await bot.send_message(
            chat_id=settings.ADMIN_ID,
            text=text,
            parse_mode=ParseMode.HTML,
        )
        return True

    elif message.photo:
        photo_id = message.photo[-1].file_id
        await bot.send_message(chat_id=settings.ADMIN_ID, text=text, parse_mode=ParseMode.HTML)
        await bot.send_photo(chat_id=settings.ADMIN_ID, photo=photo_id)
        return True

    elif message.video:
        await bot.send_message(chat_id=settings.ADMIN_ID, text=text, parse_mode=ParseMode.HTML)
        await bot.send_video(chat_id=settings.ADMIN_ID, video=message.video.file_id)
        return True

    await answer_msg(message, msg_text("invalid_content", profile.language))
    return False


async def send_program(client: Client, client_lang: str, program_text: str, state: FSMContext) -> None:
    await send_message(
        recipient=client,
        text=msg_text("new_program", client_lang),
        state=state,
        include_incoming_message=False,
    )
    await send_message(
        recipient=client,
        text=msg_text("program_page", client_lang).format(program=program_text, day=1),
        state=state,
        reply_markup=program_view_kb(client_lang),
        include_incoming_message=False,
    )
