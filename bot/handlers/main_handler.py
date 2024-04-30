import loguru
from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import profile_menu_keyboard
from bot.states import States
from common.functions import show_main_menu, update_profile
from common.models import Profile
from common.user_service import user_service
from texts.text_manager import MessageText, translate

main_router = Router()
logger = loguru.logger


@main_router.callback_query(States.main_menu)
async def main_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.from_dict(data["profile"])
    match callback_query.data:
        case "feedback":
            await callback_query.message.answer(text=translate(MessageText.feedback, lang=profile.language))
            await state.set_state(States.feedback)
        case "my_profile":
            if profile.status == "client":
                client = user_service.storage.get_client_by_id(profile.id)  # TODO: IMPLEMENT
                text = translate(MessageText.client_profile, lang=profile.language)  # TODO: ADD FORMAT HERE
            else:
                text = translate(MessageText.coach_profile, lang=profile.language)  # TODO: ADD FORMAT HERE

            await callback_query.message.answer(
                text=text,
                reply_markup=profile_menu_keyboard(profile.language),
            )
            await state.set_state(States.profile)
        case "my_clients":
            await callback_query.message.answer(text="Ваши клиенты: ")  # TODO: IMPLEMENT
        case "my_program":
            await callback_query.message.answer(text="Программа")  # TODO: IMPLEMENT
        case "my_subscription":
            await callback_query.message.answer(text="Подписка")  # TODO: IMPLEMENT
    await callback_query.message.delete()


@main_router.callback_query(States.profile)
async def profile_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.from_dict(data["profile"])
    if callback_query.data == "edit_profile":
        await update_profile(callback_query.message, profile, state)
    elif callback_query.data == "back":
        await show_main_menu(callback_query.message, profile, state)


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
    if user_data := await user_service.get_user_data(auth_token):
        if await user_service.send_feedback(user_data.get("email"), user_data.get("username"), message.text):
            logger.info(f"{user_data.get('username')} sent feedback")
            await message.answer(text=translate(MessageText.feedback_sent, lang=profile.language))
        else:
            await message.answer(text=translate(MessageText.unexpected_error, lang=profile.language))
        await show_main_menu(message, profile, state)
    else:
        await message.answer(text=translate(MessageText.unexpected_error, lang=profile.language))
        await show_main_menu(message, profile, state)
