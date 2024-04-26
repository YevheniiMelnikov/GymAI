import loguru
from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.states import States
from common.functions import show_main_menu
from common.models import Profile
from common.user_service import user_service
from texts.text_manager import MessageText, translate

main_router = Router()
logger = loguru.logger


@main_router.callback_query(States.client_menu)
async def client_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = user_service.storage.get_current_profile_by_tg_id(data["id"])
    if callback_query.data == "my_program":
        await callback_query.message.answer(text="Программа в разработке")
    elif callback_query.data == "feedback":
        await callback_query.message.answer(text=translate(MessageText.feedback, lang=profile.language))
        await state.set_state(States.feedback)
    elif callback_query.data == "my_profile":
        await callback_query.message.answer(text="Ваш профиль: ")
    await callback_query.message.delete()
    await state.clear()


@main_router.callback_query(States.coach_menu)
async def coach_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = user_service.storage.get_current_profile_by_tg_id(data["id"])  # TODO: ADD MY PROFILE
    if callback_query.data == "show_my_clients":
        await callback_query.message.answer(text="Ваши клиенты: ")
    elif callback_query.data == "feedback":
        await callback_query.message.answer(text=translate(MessageText.feedback, lang=profile.language))
        await state.set_state(States.feedback)
    await callback_query.message.delete()
    await state.clear()


@main_router.message(States.password_reset)
async def process_password_reset(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    index = next((i for i, username in enumerate(data["usernames"]) if username == message.text), None)
    if index is not None and data["emails"][index]:
        email = data["emails"][index]
        profile = Profile.from_dict(data["profiles"][index])
        if await user_service.reset_password(email):
            await message.answer(text=translate(MessageText.password_reset_sent, profile.language).format(email=email))
            await message.answer(text=translate(MessageText.username, profile.language))
            await state.set_state(States.username)
        else:
            await message.answer(text=translate(MessageText.unexpected_error, profile.language))
    else:
        await message.answer(text=translate(MessageText.no_profiles_found, data["lang"]))
        await message.answer(text=translate(MessageText.help, data["lang"]))
    await message.delete()


@main_router.message(States.feedback)
async def handle_feedback(message: Message, state: FSMContext) -> None:
    profile = user_service.storage.get_current_profile_by_tg_id(message.from_user.id)
    auth_token = user_service.storage.get_profile_info_by_key(message.from_user.id, profile.id, "auth_token")
    if user_data := await user_service.get_user_data_by_token(auth_token):
        if await user_service.send_feedback(user_data.get("email"), user_data.get("username"), message.text):
            logger.info(f"{user_data.get('username')} sent feedback")
            await message.answer(text=translate(MessageText.feedback_sent, lang=profile.language))
        else:
            await message.answer(text=translate(MessageText.unexpected_error, lang=profile.language))
        await show_main_menu(message, state, profile.language)
    else:
        await message.answer(text=translate(MessageText.unexpected_error, lang=profile.language))
        await show_main_menu(message, state, profile.language)
