from common.logger import logger
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import new_message_kb
from bot.states import States
from core.cache_manager import CacheManager
from core.exceptions import UserServiceError
from functions.chat import send_message
from core.models import Profile
from functions.menus import show_main_menu
from functions.profiles import get_or_load_profile
from bot.texts.text_manager import msg_text
from services.profile_service import ProfileService


chat_router = Router()


@chat_router.message(States.contact_client, F.text | F.photo | F.video)
async def contact_client(message: Message, state: FSMContext):
    data = await state.get_data()
    profile = await get_or_load_profile(message.from_user.id)

    try:
        client = CacheManager.get_client_by_id(data.get("recipient_id"))
        if client.status == "waiting_for_text":
            CacheManager.set_client_data(client.id, {"status": "default"})
        client_profile = Profile.from_dict(await ProfileService.get_profile(client.id))
        coach_name = CacheManager.get_coach_by_id(profile.id).name
    except Exception as e:
        logger.error(f"Can't get data: {e}")
        await message.answer(msg_text("unexpected_error", profile.language))
        await show_main_menu(message, profile, state)
        return

    await state.update_data(sender_name=coach_name)
    await state.update_data(recipient_language=client_profile.language)

    if message.photo:
        photo = message.photo[-1]
        caption = message.caption if message.caption else ""
        await send_message(
            client, caption, state, reply_markup=new_message_kb(client_profile.language, profile.id), photo=photo
        )
    elif message.video:
        video = message.video
        caption = message.caption if message.caption else ""
        await send_message(
            client, caption, state, reply_markup=new_message_kb(client_profile.language, profile.id), video=video
        )
    else:
        await send_message(
            client, message.text, state, reply_markup=new_message_kb(client_profile.language, profile.id)
        )

    await message.answer(msg_text("message_sent", profile.language))
    logger.debug(f"Coach {profile.id} sent message to client {client.id}")
    await show_main_menu(message, profile, state)


@chat_router.message(States.contact_coach, F.text | F.photo | F.video)
async def contact_coach(message: Message, state: FSMContext):
    data = await state.get_data()
    profile = await get_or_load_profile(message.from_user.id)

    try:
        coach = CacheManager.get_coach_by_id(data.get("recipient_id"))
        if not coach:
            raise UserServiceError("Coach not found in cache", 404, f"recipient_id: {data.get('recipient_id')}")

        coach_profile = Profile.from_dict(await ProfileService.get_profile(coach.id))
        if not coach_profile:
            raise UserServiceError("Coach profile not found", 404, f"coach_id: {coach.id}")

        client_name = CacheManager.get_client_by_id(profile.id).name
        if not client_name:
            raise UserServiceError("Client name not found", 404, f"profile_id: {profile.id}")

    except UserServiceError as error:
        logger.error(f"UserServiceError - {error}")
        await message.answer(msg_text("unexpected_error", profile.language))
        await show_main_menu(message, profile, state)
        return
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        await message.answer(msg_text("unexpected_error", profile.language))
        await show_main_menu(message, profile, state)
        return

    await state.update_data(sender_name=client_name)
    await state.update_data(recipient_language=coach_profile.language)

    if message.photo:
        photo = message.photo[-1]
        caption = message.caption if message.caption else ""
        await send_message(
            coach, caption, state, reply_markup=new_message_kb(coach_profile.language, profile.id), photo=photo
        )
    elif message.video:
        video = message.video
        caption = message.caption if message.caption else ""
        await send_message(
            coach, caption, state, reply_markup=new_message_kb(coach_profile.language, profile.id), video=video
        )
    else:
        await send_message(coach, message.text, state, reply_markup=new_message_kb(coach_profile.language, profile.id))

    await message.answer(msg_text("message_sent", profile.language))
    logger.debug(f"Client {profile.id} sent message to coach {coach.id}")
    await show_main_menu(message, profile, state)
