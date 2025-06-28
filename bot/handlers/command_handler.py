from contextlib import suppress

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from core.enums import CommandName
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import select_language_kb
from bot.states import States
from loguru import logger
from config.env_settings import settings
from core.cache import Cache
from core.exceptions import ProfileNotFoundError
from core.schemas import Profile
from bot.utils.menus import show_main_menu
from bot.texts.text_manager import msg_text

cmd_router = Router()


@cmd_router.message(Command(CommandName.language))
async def cmd_language(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile", {})
    profile = Profile.model_validate(profile_data) if profile_data else None
    lang = profile.language if profile else settings.DEFAULT_LANG
    await message.answer(msg_text("select_language", lang), reply_markup=select_language_kb())
    await state.set_state(States.select_language)
    with suppress(TelegramBadRequest):
        await message.delete()


@cmd_router.message(Command(CommandName.menu))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile", {})
    profile = Profile.model_validate(profile_data) if profile_data else None
    if profile:
        await show_main_menu(message, profile, state)
    else:
        await state.set_state(States.select_language)
        await message.answer(msg_text("select_language", settings.DEFAULT_LANG), reply_markup=select_language_kb())

    with suppress(TelegramBadRequest):
        await message.delete()


@cmd_router.message(Command(CommandName.start))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not message.from_user:
        return

    try:
        profile = await Cache.profile.get_profile(message.from_user.id)
        await state.update_data(lang=profile.language, profile=profile.model_dump())
        await show_main_menu(message, profile, state)
        with suppress(TelegramBadRequest):
            await message.delete()
    except ProfileNotFoundError:
        logger.info(f"Telegram user {message.from_user.id} started bot")
        start_msg = await message.answer(msg_text("start", settings.DEFAULT_LANG))
        language_msg = await message.answer(
            msg_text("select_language", settings.DEFAULT_LANG), reply_markup=select_language_kb()
        )
        message_ids = []
        if start_msg:
            message_ids.append(start_msg.message_id)
        if language_msg:
            message_ids.append(language_msg.message_id)
        await state.update_data(message_ids=message_ids, chat_id=message.from_user.id)
        await state.set_state(States.select_language)
        with suppress(TelegramBadRequest):
            await message.delete()


@cmd_router.message(Command(CommandName.help))
async def cmd_help(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile", {})
    profile = Profile.model_validate(profile_data) if profile_data else None
    language = profile.language if profile else settings.DEFAULT_LANG
    await message.answer(msg_text("help", language))


@cmd_router.message(Command(CommandName.feedback))
async def cmd_feedback(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile", {})
    profile = Profile.model_validate(profile_data) if profile_data else None
    language = profile.language if profile else settings.DEFAULT_LANG
    await message.answer(msg_text("feedback", language))
    await state.set_state(States.feedback)
    with suppress(TelegramBadRequest):
        await message.delete()


@cmd_router.message(Command(CommandName.offer))
async def cmd_policy(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile", {})
    profile = Profile.model_validate(profile_data) if profile_data else None
    lang = profile.language if profile else settings.DEFAULT_LANG
    await message.answer(
        msg_text("contract_info_message", lang).format(
            public_offer=settings.PUBLIC_OFFER,
            privacy_policy=settings.PRIVACY_POLICY,
        ),
        disable_web_page_preview=True,
    )
    with suppress(TelegramBadRequest):
        await message.delete()


@cmd_router.message(Command(CommandName.info))
async def cmd_info(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile", {})
    profile = Profile.model_validate(profile_data) if profile_data else None
    lang = profile.language if profile else settings.DEFAULT_LANG
    await message.answer(
        msg_text("info", lang).format(
            offer=settings.PUBLIC_OFFER, email=settings.EMAIL, tg=settings.TG_SUPPORT_CONTACT
        ),
        disable_web_page_preview=True,
    )
    with suppress(TelegramBadRequest):
        await message.delete()
