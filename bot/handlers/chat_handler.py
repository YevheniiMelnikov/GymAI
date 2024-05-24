import loguru
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import incoming_message
from bot.states import States
from common.exceptions import UserServiceError
from common.functions import send_message, show_main_menu
from common.user_service import user_service
from texts.text_manager import MessageText, translate

logger = loguru.logger
chat_router = Router()


@chat_router.message(States.contact_client, F.text)
async def contact_client(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    sender = user_service.storage.get_current_profile(message.from_user.id)

    try:
        recipient = user_service.storage.get_client_by_id(data.get("recipient_id"))
        sender_name = user_service.storage.get_coach_by_id(sender.id).name
    except UserServiceError as error:
        logger.error(f"Can't get data from cache: {error}")
        await message.answer(translate(MessageText.unexpected_error, sender.language))
        await state.set_state(States.main_menu)
        await show_main_menu(message, sender, state)
        return

    await state.update_data(sender_name=sender_name)
    recipient_language = user_service.storage.get_profile_info_by_key(recipient.tg_id, recipient.id, "language")
    await state.update_data(recipient_language=recipient_language)
    await send_message(
        recipient, message.text, bot, state, reply_markup=incoming_message(recipient_language, sender.id)
    )
    await message.answer(translate(MessageText.message_sent, sender.language))
    logger.info(f"Coach {sender.id} sent message to client {recipient.id}")
    await state.set_state(States.main_menu)
    await show_main_menu(message, sender, state)


@chat_router.message(States.contact_coach, F.text)
async def contact_coach(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    sender = user_service.storage.get_current_profile(message.from_user.id)

    try:
        recipient = user_service.storage.get_coach_by_id(data.get("recipient_id"))
        sender_name = user_service.storage.get_client_by_id(sender.id).name
    except UserServiceError as error:
        logger.error(f"Can't get data from cache: {error}")
        await message.answer(translate(MessageText.unexpected_error, sender.language))
        await state.set_state(States.main_menu)
        await show_main_menu(message, sender, state)
        return

    await state.update_data(sender_name=sender_name)
    recipient_language = user_service.storage.get_profile_info_by_key(recipient.tg_id, recipient.id, "language")
    await state.update_data(recipient_language=recipient_language)
    await send_message(
        recipient, message.text, bot, state, reply_markup=incoming_message(recipient_language, sender.id)
    )
    await message.answer(translate(MessageText.message_sent, sender.language))
    logger.info(f"Client {sender.id} sent message to coach {recipient.id}")
    await state.set_state(States.main_menu)
    await show_main_menu(message, sender, state)
