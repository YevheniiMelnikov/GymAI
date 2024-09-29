import os

import loguru
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import action_choice_keyboard, language_choice
from bot.states import States
from common.cache_manager import cache_manager
from functions.menus import show_main_menu
from functions.profiles import get_or_load_profile
from services.user_service import user_service
from texts.resources import MessageText
from texts.text_manager import translate

logger = loguru.logger
cmd_router = Router()


@cmd_router.message(Command("language"))
async def cmd_language(message: Message, state: FSMContext) -> None:
    if profile := await get_or_load_profile(message.from_user.id):
        lang = profile.language
    else:
        lang = "ua"
    await message.answer(text=translate(MessageText.choose_language, lang=lang), reply_markup=language_choice())
    await state.set_state(States.language_choice)


@cmd_router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    if profile := await get_or_load_profile(message.from_user.id):
        await show_main_menu(message, profile, state)
    else:
        await state.set_state(States.language_choice)
        await message.answer(text=translate(MessageText.choose_language), reply_markup=language_choice())


@cmd_router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(chat_id=message.chat.id)
    if profile := await get_or_load_profile(message.from_user.id):
        logger.info(f"User with profile_id {profile.id} started bot")
        auth_token = await user_service.get_user_token(profile.id)
        await user_service.log_out(profile, auth_token)
        cache_manager.deactivate_profiles(profile.current_tg_id)
        await state.update_data(lang=profile.language)
        start_message = await message.answer(text=translate(MessageText.start, profile.language))
        await message.answer(
            text=translate(MessageText.choose_action, lang=profile.language),
            reply_markup=action_choice_keyboard(profile.language),
        )
        await state.update_data(message_ids=[start_message.message_id])
        await state.set_state(States.action_choice)
        await message.delete()
        return

    logger.info(f"Telegram user {message.from_user.id} started bot")
    start_message = await message.answer(text=translate(MessageText.start))
    await state.update_data(message_ids=[start_message.message_id])
    await state.set_state(States.language_choice)
    language_message = await message.answer(text=translate(MessageText.choose_language), reply_markup=language_choice())
    await state.update_data(message_ids=[start_message.message_id, language_message.message_id])


@cmd_router.message(Command("logout"))
async def cmd_logout(message: Message, state: FSMContext) -> None:
    await state.clear()
    if profile := await get_or_load_profile(message.from_user.id):
        language = profile.language if profile.language else "ua"
        auth_token = await user_service.get_user_token(profile.id)
        await user_service.log_out(profile, auth_token)
        cache_manager.deactivate_profiles(profile.current_tg_id)
        await state.update_data(lang=language)
        await message.answer(
            text=translate(MessageText.choose_action, lang=language),
            reply_markup=action_choice_keyboard(language),
        )
        await state.set_state(States.action_choice)

    else:
        await message.answer(text=translate(MessageText.logout, lang="ua"))


@cmd_router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    profile = await get_or_load_profile(message.from_user.id)
    language = profile.language if profile else "ua"
    await message.answer(text=translate(MessageText.help, lang=language))


@cmd_router.message(Command("feedback"))
async def cmd_feedback(message: Message, state: FSMContext) -> None:
    profile = await get_or_load_profile(message.from_user.id)
    language = profile.language if profile else "ua"
    await message.answer(text=translate(MessageText.feedback, lang=language))
    await state.set_state(States.feedback)


@cmd_router.message(Command("reset_password"))
async def cmd_reset_password(message: Message, state: FSMContext) -> None:
    profiles = cache_manager.get_profiles(message.from_user.id)
    if profiles:
        usernames = [
            cache_manager.get_profile_info_by_key(message.from_user.id, profile.id, "username") for profile in profiles
        ]
        language = profiles[0].language if profiles[0].language else "ua"
        await state.update_data(
            lang=language, profiles=[profile.to_dict() for profile in profiles], usernames=usernames
        )
        await message.answer(text=translate(MessageText.username, language))
        await state.set_state(States.password_reset)
    else:
        await message.answer(text=translate(MessageText.no_profiles_found))
        await state.clear()


@cmd_router.message(Command("offer"))
async def cmd_policy(message: Message) -> None:
    if profile := await get_or_load_profile(message.from_user.id):
        language = profile.language
    else:
        language = "ua"
    public_offer = os.getenv("PUBLIC_OFFER")
    privacy_policy = os.getenv("PRIVACY_POLICY")
    await message.answer(
        translate(MessageText.contract_info_message, language).format(
            public_offer=public_offer,
            privacy_policy=privacy_policy,
        ),
        disable_web_page_preview=True,
    )


@cmd_router.message(Command("info"))
async def cmd_info(message: Message, state: FSMContext) -> None:
    if profile := await get_or_load_profile(message.from_user.id):
        language = profile.language
    else:
        language = "ua"
    await message.answer(
        translate(MessageText.info, language).format(
            offer=os.getenv("PUBLIC_OFFER"), email=os.getenv("DEFAULT_FROM_EMAIL"), tg=os.getenv("TG_SUPPORT_CONTACT")
        ),
        disable_web_page_preview=True,
    )
