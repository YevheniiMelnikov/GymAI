import loguru
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.states import States
from common.functions import send_message, show_clients, show_main_menu
from common.user_service import user_service
from texts.text_manager import MessageText, translate

logger = loguru.logger
chat_router = Router()


@chat_router.message(States.contact_client, F.text)
async def contact_client(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    recipient = user_service.storage.get_client_by_id(data["recipient"])
    sender = user_service.storage.get_current_profile(message.from_user.id)
    await send_message(recipient, message, bot, state, sender)
    await message.answer(translate(MessageText.message_sent, sender.language))
    logger.info(f"Coach {sender.id} sent message to client {recipient.id}")
    await state.set_state(States.main_menu)
    await show_main_menu(message, sender, state)


@chat_router.message(States.contact_coach, F.text)
async def contact_coach(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    recipient = user_service.storage.get_coach_by_id(data["recipient"])
    sender = user_service.storage.get_current_profile(message.from_user.id)
    await send_message(recipient, message, bot, state, sender)
    await message.answer(translate(MessageText.message_sent, sender.language))
    logger.info(f"Client {sender.id} sent message to coach {recipient.id}")
    await state.set_state(States.main_menu)
    await show_main_menu(message, sender, state)
