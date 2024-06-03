import loguru
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import incoming_message, workout_type
from bot.states import States
from common.exceptions import UserServiceError
from common.functions import send_message, show_main_menu
from common.user_service import user_service
from texts.text_manager import ButtonText, MessageText, translate

logger = loguru.logger
chat_router = Router()


@chat_router.message(States.contact_client, F.text)
async def contact_client(message: Message, state: FSMContext):
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
    await send_message(recipient, message.text, state, reply_markup=incoming_message(recipient_language, sender.id))
    await message.answer(translate(MessageText.message_sent, sender.language))
    logger.info(f"Coach {sender.id} sent message to client {recipient.id}")
    await state.set_state(States.main_menu)
    await show_main_menu(message, sender, state)


@chat_router.message(States.contact_coach, F.text)
async def contact_coach(message: Message, state: FSMContext):
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
    await send_message(recipient, message.text, state, reply_markup=incoming_message(recipient_language, sender.id))
    await message.answer(translate(MessageText.message_sent, sender.language))
    logger.info(f"Client {sender.id} sent message to coach {recipient.id}")
    await state.set_state(States.main_menu)
    await show_main_menu(message, sender, state)


@chat_router.callback_query(States.gift, F.data == "get")
async def get_the_gift(callback_query: CallbackQuery, state: FSMContext):
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    await callback_query.answer(translate(ButtonText.done, profile.language))
    await callback_query.message.answer(
        translate(MessageText.workout_type), reply_markup=workout_type(profile.language)
    )
    await state.update_data(new_client=True)
    await state.set_state(States.workout_type)
    await callback_query.message.delete()
