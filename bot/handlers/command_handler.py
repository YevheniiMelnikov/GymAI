from contextlib import suppress

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import select_language_kb
from bot.states import States
from common.logger import logger
from common.settings import settings
from core.models import Profile
from functions.menus import show_main_menu
from bot.texts.text_manager import msg_text
from services.profile_service import ProfileService

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
    if profile_data := await ProfileService.get_profile_by_telegram_id(message.from_user.id):
        profile = Profile.from_dict(profile_data)
        await state.update_data(lang=profile.language, profile=profile_data)
        await show_main_menu(message, profile, state)
        with suppress(TelegramBadRequest):
            await message.delete()
    else:
        logger.info(f"Telegram user {message.from_user.id} started bot")
        start_msg = await message.answer(msg_text("start", settings.DEFAULT_BOT_LANGUAGE))
        language_msg = await message.answer(
            msg_text("select_language", settings.DEFAULT_BOT_LANGUAGE), reply_markup=select_language_kb()
        )
        await state.set_state(States.select_language)
        await state.update_data(message_ids=[start_msg.message_id, language_msg.message_id])
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
