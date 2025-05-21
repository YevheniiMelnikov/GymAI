from contextlib import suppress

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import select_language_kb
from bot.states import States
from loguru import logger
from config.env_settings import Settings
from core.models import Profile
from functions.menus import show_main_menu
from bot.texts.text_manager import msg_text
from functions.profiles import get_user_profile

cmd_router = Router()


@cmd_router.message(Command("language"))
async def cmd_language(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile", {})
    profile = Profile.model_validate(profile_data) if profile_data else None
    lang = profile.language if profile else Settings.BOT_LANG
    await message.answer(msg_text("select_language", lang), reply_markup=select_language_kb())
    await state.set_state(States.select_language)
    with suppress(TelegramBadRequest):
        await message.delete()


@cmd_router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile", {})
    profile = Profile.model_validate(profile_data) if profile_data else None
    if profile:
        await show_main_menu(message, profile, state)
    else:
        await state.set_state(States.select_language)
        await message.answer(msg_text("select_language", Settings.BOT_LANG), reply_markup=select_language_kb())

    with suppress(TelegramBadRequest):
        await message.delete()


@cmd_router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    if profile := await get_user_profile(message.from_user.id):
        await state.update_data(lang=profile.language, profile=profile.model_dump())
        await show_main_menu(message, profile, state)
        with suppress(TelegramBadRequest):
            await message.delete()
    else:
        logger.info(f"Telegram user {message.from_user.id} started bot")
        start_msg = await message.answer(msg_text("start", Settings.BOT_LANG))
        language_msg = await message.answer(
            msg_text("select_language", Settings.BOT_LANG), reply_markup=select_language_kb()
        )
        await state.set_state(States.select_language)
        await state.update_data(message_ids=[start_msg.message_id, language_msg.message_id])
        with suppress(TelegramBadRequest):
            await message.delete()


@cmd_router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile", {})
    profile = Profile.model_validate(profile_data) if profile_data else None
    language = profile.language if profile else Settings.BOT_LANG
    await message.answer(msg_text("help", language))


@cmd_router.message(Command("feedback"))
async def cmd_feedback(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile", {})
    profile = Profile.model_validate(profile_data) if profile_data else None
    language = profile.language if profile else Settings.BOT_LANG
    await message.answer(msg_text("feedback", language))
    await state.set_state(States.feedback)
    with suppress(TelegramBadRequest):
        await message.delete()


@cmd_router.message(Command("offer"))
async def cmd_policy(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile", {})
    profile = Profile.model_validate(profile_data) if profile_data else None
    lang = profile.language if profile else Settings.BOT_LANG
    await message.answer(
        msg_text("contract_info_message", lang).format(
            public_offer=Settings.PUBLIC_OFFER,
            privacy_policy=Settings.PRIVACY_POLICY,
        ),
        disable_web_page_preview=True,
    )
    with suppress(TelegramBadRequest):
        await message.delete()


@cmd_router.message(Command("info"))
async def cmd_info(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile", {})
    profile = Profile.model_validate(profile_data) if profile_data else None
    lang = profile.language if profile else Settings.BOT_LANG
    await message.answer(
        msg_text("info", lang).format(
            offer=Settings.PUBLIC_OFFER, email=Settings.EMAIL, tg=Settings.TG_SUPPORT_CONTACT
        ),
        disable_web_page_preview=True,
    )
    with suppress(TelegramBadRequest):
        await message.delete()
