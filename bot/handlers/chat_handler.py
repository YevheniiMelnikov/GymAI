import loguru
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import incoming_message
from bot.states import States
from common.backend_service import backend_service
from common.cache_manager import cache_manager
from common.exceptions import UserServiceError
from common.functions.chat import send_message
from common.functions.menus import show_main_menu
from common.models import Profile
from texts.resources import MessageText
from texts.text_manager import translate

logger = loguru.logger
chat_router = Router()


@chat_router.message(States.contact_client, F.text | F.photo)
async def contact_client(message: Message, state: FSMContext):
    data = await state.get_data()
    coach = cache_manager.get_current_profile(message.from_user.id)

    try:
        client = cache_manager.get_client_by_id(data.get("recipient_id"))
        if client.status == "waiting_for_text":
            cache_manager.set_client_data(client.id, {"status": "default"})
        client_profile = Profile.from_dict(await backend_service.get_profile(client.id))
        coach_name = cache_manager.get_coach_by_id(coach.id).name
    except Exception as e:
        logger.error(f"Can't get data: {e}")
        await message.answer(translate(MessageText.unexpected_error, coach.language))
        await show_main_menu(message, coach, state)
        return

    await state.update_data(sender_name=coach_name)
    client_language = cache_manager.get_profile_info_by_key(client_profile.current_tg_id, client.id, "language")
    await state.update_data(recipient_language=client_language)

    if message.photo:
        photo = message.photo[-1]
        caption = message.caption if message.caption else ""
        await send_message(
            client, caption, state, reply_markup=incoming_message(client_language, coach.id), photo=photo
        )
    else:
        await send_message(client, message.text, state, reply_markup=incoming_message(client_language, coach.id))

    await message.answer(translate(MessageText.message_sent, coach.language))
    logger.debug(f"Coach {coach.id} sent message to client {client.id}")
    await show_main_menu(message, coach, state)


@chat_router.message(States.contact_coach, F.text | F.photo)
async def contact_coach(message: Message, state: FSMContext):
    data = await state.get_data()
    client = cache_manager.get_current_profile(message.from_user.id)

    try:
        coach = cache_manager.get_coach_by_id(data.get("recipient_id"))
        client_name = cache_manager.get_client_by_id(client.id).name
    except UserServiceError as error:
        logger.error(f"Can't get data from cache: {error}")
        await message.answer(translate(MessageText.unexpected_error, client.language))
        await show_main_menu(message, client, state)
        return

    await state.update_data(sender_name=client_name)
    coach_data = await backend_service.get_profile(coach.id)
    coach_lang = cache_manager.get_profile_info_by_key(coach_data.get("current_tg_id"), coach.id, "language") or "ua"
    await state.update_data(recipient_language=coach_lang)

    if message.photo:
        photo = message.photo[-1]
        caption = message.caption if message.caption else ""
        await send_message(coach, caption, state, reply_markup=incoming_message(coach_lang, client.id), photo=photo)
    else:
        await send_message(coach, message.text, state, reply_markup=incoming_message(coach_lang, client.id))

    await message.answer(translate(MessageText.message_sent, client.language))
    logger.debug(f"Client {client.id} sent message to coach {coach.id}")
    await show_main_menu(message, client, state)
