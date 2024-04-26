import loguru
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import language_choice
from bot.states import States
from common.user_service import user_service
from texts.text_manager import MessageText, translate

logger = loguru.logger
cmd_router = Router()


@cmd_router.message(Command("language"))
async def cmd_language(message: Message, state: FSMContext) -> None:
    profile = user_service.session.get_current_profile_by_tg_id(message.from_user.id)
    lang = profile.language if profile else None
    await message.answer(text=translate(MessageText.choose_language, lang=lang), reply_markup=language_choice())
    await state.set_state(States.language_choice)


@cmd_router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    logger.info(f"User {message.from_user.id} started bot")
    await state.clear()
    await message.answer(text=translate(MessageText.start))
    if user_service.session.get_current_profile_by_tg_id(message.from_user.id):
        await user_service.log_out(message.from_user.id)
    await message.delete()
    await state.set_state(States.language_choice)
    await message.answer(text=translate(MessageText.choose_language), reply_markup=language_choice())


@cmd_router.message(Command("logout"))
async def cmd_logout(message: Message, state: FSMContext) -> None:
    profile = user_service.session.get_current_profile_by_tg_id(message.from_user.id)
    language = profile.language if profile else None
    await state.clear()
    await user_service.log_out(message.from_user.id)
    await message.answer(text=translate(MessageText.logout, lang=language))


@cmd_router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    profile = user_service.session.get_current_profile_by_tg_id(message.from_user.id)
    language = profile.language if profile else None
    await message.answer(text=translate(MessageText.help, lang=language))


@cmd_router.message(Command("feedback"))
async def cmd_feedback(message: Message, state: FSMContext) -> None:
    profile = user_service.session.get_current_profile_by_tg_id(message.from_user.id)
    language = profile.language if profile else None
    await message.answer(text=translate(MessageText.feedback, lang=language))
    await state.set_state(States.feedback)


@cmd_router.message(Command("reset_password"))
async def cmd_reset_password(message: Message, state: FSMContext) -> None:
    profiles = user_service.session.get_profiles(message.from_user.id)
    if profiles:
        usernames = [
            user_service.session.get_profile_info_by_key(message.from_user.id, profile.id, "username")
            for profile in profiles
        ]
        emails = [
            user_service.session.get_profile_info_by_key(message.from_user.id, profile.id, "email")
            for profile in profiles
        ]
        profiles_data = [profile.to_dict() for profile in profiles]
        language = profiles[0].language if profiles[0].language else None
        await state.update_data(lang=language, profiles=profiles_data, usernames=usernames, emails=emails)
        await message.answer(text=translate(MessageText.username, language))
        await state.set_state(States.password_reset)
    else:
        await message.answer(text=translate(MessageText.no_profiles_found))
