import loguru
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import incoming_message
from bot.states import States
from common.cache_manager import cache_manager
from common.exceptions import UserServiceError
from common.functions.chat import send_message
from common.functions.menus import show_main_menu
from common.functions.profiles import get_or_load_profile
from common.models import Profile
from services.profile_service import profile_service
from texts.resources import MessageText
from texts.text_manager import translate

logger = loguru.logger
chat_router = Router()


@chat_router.message(States.contact_client, F.text | F.photo | F.video)
async def contact_client(message: Message, state: FSMContext):
    data = await state.get_data()
    profile = await get_or_load_profile(message.from_user.id)

    try:
        client = cache_manager.get_client_by_id(data.get("recipient_id"))
        if client.status == "waiting_for_text":
            cache_manager.set_client_data(client.id, {"status": "default"})
        client_profile = Profile.from_dict(await profile_service.get_profile(client.id))
        coach_name = cache_manager.get_coach_by_id(profile.id).name
    except Exception as e:
        logger.error(f"Can't get data: {e}")
        await message.answer(translate(MessageText.unexpected_error, profile.language))
        await show_main_menu(message, profile, state)
        return

    await state.update_data(sender_name=coach_name)
    client_language = cache_manager.get_profile_info_by_key(client_profile.current_tg_id, client.id, "language")
    await state.update_data(recipient_language=client_language)

    if message.photo:
        photo = message.photo[-1]
        caption = message.caption if message.caption else ""
        await send_message(
            client, caption, state, reply_markup=incoming_message(client_language, profile.id), photo=photo
        )
    elif message.video:
        video = message.video
        caption = message.caption if message.caption else ""
        await send_message(
            client, caption, state, reply_markup=incoming_message(client_language, profile.id), video=video
        )
    else:
        await send_message(client, message.text, state, reply_markup=incoming_message(client_language, profile.id))

    await message.answer(translate(MessageText.message_sent, profile.language))
    logger.debug(f"Coach {profile.id} sent message to client {client.id}")
    await show_main_menu(message, profile, state)


@chat_router.message(States.contact_coach, F.text | F.photo | F.video)
async def contact_coach(message: Message, state: FSMContext):
    data = await state.get_data()
    profile = await get_or_load_profile(message.from_user.id)

    try:
        coach = cache_manager.get_coach_by_id(data.get("recipient_id"))
        client_name = cache_manager.get_client_by_id(profile.id).name
    except UserServiceError as error:
        logger.error(f"Can't get data from cache: {error}")
        await message.answer(translate(MessageText.unexpected_error, profile.language))
        await show_main_menu(message, profile, state)
        return

    await state.update_data(sender_name=client_name)
    coach_data = await profile_service.get_profile(coach.id)
    coach_lang = cache_manager.get_profile_info_by_key(coach_data.get("current_tg_id"), coach.id, "language") or "ua"
    await state.update_data(recipient_language=coach_lang)

    if message.photo:
        photo = message.photo[-1]
        caption = message.caption if message.caption else ""
        await send_message(coach, caption, state, reply_markup=incoming_message(coach_lang, profile.id), photo=photo)
    elif message.video:
        video = message.video
        caption = message.caption if message.caption else ""
        await send_message(coach, caption, state, reply_markup=incoming_message(coach_lang, profile.id), video=video)
    else:
        await send_message(coach, message.text, state, reply_markup=incoming_message(coach_lang, profile.id))

    await message.answer(translate(MessageText.message_sent, profile.language))
    logger.debug(f"Client {profile.id} sent message to coach {coach.id}")
    await show_main_menu(message, profile, state)
