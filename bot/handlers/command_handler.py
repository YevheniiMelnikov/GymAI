from contextlib import suppress

import loguru
from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import action_choice_kb, select_language_kb
from bot.states import States
from core.cache_manager import cache_manager
from common.settings import settings
from core.models import Profile
from functions.menus import show_main_menu
from services.user_service import user_service
from bot.texts.text_manager import msg_text

logger = loguru.logger
cmd_router = Router()


@cmd_router.message(Command("language"))
async def cmd_language(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.from_dict(data.get("profile", {}))
    lang = profile.language if profile else settings.DEFAULT_BOT_LANGUAGE
    await message.answer(msg_text("select_language", lang), reply_markup=select_language_kb())
    await state.set_state(States.select_language)
    with suppress(TelegramBadRequest):
        await message.delete()


@cmd_router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if profile := Profile.from_dict(data.get("profile", {})):
        await show_main_menu(message, profile, state)
    else:
        await state.set_state(States.select_language)
        await message.answer(msg_text("select_language", profile.language), reply_markup=select_language_kb())

    with suppress(TelegramBadRequest):
        await message.delete()


@cmd_router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(chat_id=message.chat.id)
    data = await state.get_data()
    if profile := Profile.from_dict(data.get("profile", {})):
        logger.info(f"User with profile_id {profile.id} started bot")
        auth_token = await user_service.get_user_token(profile.id)
        await user_service.log_out(profile, auth_token)
        cache_manager.deactivate_profiles(profile.current_tg_id)
        await state.update_data(lang=profile.language)
        start_message = await message.answer(msg_text("start", profile.language))
        await message.answer(
            msg_text("select_action", profile.language),
            reply_markup=action_choice_kb(profile.language),
        )
        await state.update_data(message_ids=[start_message.message_id])
        await state.set_state(States.action_choice)
        with suppress(TelegramBadRequest):
            await message.delete()
        return

    logger.info(f"Telegram user {message.from_user.id} started bot")
    start_message = await message.answer(msg_text("start", settings.DEFAULT_BOT_LANGUAGE))
    await state.update_data(message_ids=[start_message.message_id])
    await state.set_state(States.select_language)
    language_message = await message.answer(
        msg_text("select_language", settings.DEFAULT_BOT_LANGUAGE), reply_markup=select_language_kb()
    )
    await state.update_data(message_ids=[start_message.message_id, language_message.message_id])
    with suppress(TelegramBadRequest):
        await message.delete()


@cmd_router.message(Command("logout"))
async def cmd_logout(message: Message, state: FSMContext) -> None:
    await state.clear()
    data = await state.get_data()
    if profile := Profile.from_dict(data.get("profile", {})):
        lang = profile.language if profile.language else settings.DEFAULT_BOT_LANGUAGE
        auth_token = await user_service.get_user_token(profile.id)
        await user_service.log_out(profile, auth_token)
        cache_manager.deactivate_profiles(profile.current_tg_id)
        await state.update_data(lang=lang)
        await message.answer(
            msg_text("select_action", lang),
            reply_markup=action_choice_kb(lang),
        )
        await state.set_state(States.action_choice)

    else:
        await message.answer(msg_text("logout", settings.DEFAULT_BOT_LANGUAGE))
    with suppress(TelegramBadRequest):
        await message.delete()


@cmd_router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.from_dict(data.get("profile", {}))
    language = profile.language if profile else settings.DEFAULT_BOT_LANGUAGE
    await message.answer(msg_text("help", language))


@cmd_router.message(Command("feedback"))
async def cmd_feedback(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.from_dict(data.get("profile", {}))
    language = profile.language if profile else settings.DEFAULT_BOT_LANGUAGE
    await message.answer(msg_text("feedback", language))
    await state.set_state(States.feedback)
    with suppress(TelegramBadRequest):
        await message.delete()


@cmd_router.message(Command("reset_password"))
async def cmd_reset_password(message: Message, state: FSMContext) -> None:
    profiles = cache_manager.get_profiles(message.from_user.id)
    if profiles:
        usernames = [
            cache_manager.get_profile_info_by_key(message.from_user.id, profile.id, "username") for profile in profiles
        ]
        language = profiles[0].language if profiles[0].language else settings.DEFAULT_BOT_LANGUAGE
        await state.update_data(
            lang=language, profiles=[profile.to_dict() for profile in profiles], usernames=usernames
        )
        await message.answer(msg_text("username", language))
        await state.set_state(States.password_reset)
    else:
        await message.answer(msg_text("no_profiles_found"))
        await state.clear()

    with suppress(TelegramBadRequest):
        await message.delete()


@cmd_router.message(Command("offer"))
async def cmd_policy(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.from_dict(data.get("profile", {}))
    lang = profile.language if profile else settings.DEFAULT_BOT_LANGUAGE
    await message.answer(
        msg_text("contract_info_message", lang).format(
            public_offer=settings.PUBLIC_OFFER,
            privacy_policy=settings.PRIVACY_POLICY,
        ),
        disable_web_page_preview=True,
    )
    with suppress(TelegramBadRequest):
        await message.delete()


@cmd_router.message(Command("info"))
async def cmd_info(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.from_dict(data.get("profile", {}))
    lang = profile.language if profile else settings.DEFAULT_BOT_LANGUAGE
    await message.answer(
        msg_text("info", lang).format(
            offer=settings.PUBLIC_OFFER, email=settings.DEFAULT_FROM_EMAIL, tg=settings.TG_SUPPORT_CONTACT
        ),
        disable_web_page_preview=True,
    )
    with suppress(TelegramBadRequest):
        await message.delete()
