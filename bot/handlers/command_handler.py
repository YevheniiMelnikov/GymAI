from contextlib import suppress

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from core.enums import CommandName, ProfileStatus
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import select_language_kb
from loguru import logger
from config.app_settings import settings
from core.cache import Cache
from core.exceptions import ProfileNotFoundError
from core.schemas import Profile
from bot.utils.menus import prompt_profile_completion_questionnaire, show_main_menu
from bot.utils.bot import prompt_language_selection
from bot.texts import MessageText, translate
from bot.utils.urls import get_webapp_url
from bot.states import States
from core.services import APIService

cmd_router = Router()


@cmd_router.message(Command(CommandName.language))
async def cmd_language(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile", {})
    profile = Profile.model_validate(profile_data) if profile_data else None
    lang = profile.language if profile else settings.DEFAULT_LANG
    await message.answer(translate(MessageText.select_language, lang), reply_markup=select_language_kb())
    await state.set_state(States.select_language)
    with suppress(TelegramBadRequest):
        await message.delete()


@cmd_router.message(Command(CommandName.menu))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return

    try:
        profile = await APIService.profile.get_profile_by_tg_id(message.from_user.id)
        if profile is None or profile.status == ProfileStatus.deleted:
            raise ProfileNotFoundError(message.from_user.id)
        if profile.status != ProfileStatus.completed:
            await state.update_data(
                lang=profile.language or settings.DEFAULT_LANG, profile=profile.model_dump(mode="json")
            )
            await prompt_profile_completion_questionnaire(message, profile, state)
            with suppress(TelegramBadRequest):
                await message.delete()
            return
        await Cache.profile.save_record(profile.id, profile.model_dump(mode="json"))
        await state.update_data(lang=profile.language, profile=profile.model_dump(mode="json"))
        await show_main_menu(message, profile, state)
        with suppress(TelegramBadRequest):
            await message.delete()
    except ProfileNotFoundError:
        data = await state.get_data()
        lang = data.get("lang", settings.DEFAULT_LANG)
        await message.answer(translate(MessageText.finish_registration, lang))


@cmd_router.message(Command(CommandName.start))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not message.from_user:
        return

    try:
        profile = await APIService.profile.get_profile_by_tg_id(message.from_user.id)
        if profile is None or profile.status == ProfileStatus.deleted:
            raise ProfileNotFoundError(message.from_user.id)
        if profile.status != ProfileStatus.completed:
            await state.update_data(
                lang=profile.language or settings.DEFAULT_LANG, profile=profile.model_dump(mode="json")
            )
            await prompt_profile_completion_questionnaire(message, profile, state)
            with suppress(TelegramBadRequest):
                await message.delete()
            return
        await Cache.profile.save_record(profile.id, profile.model_dump(mode="json"))
        await state.update_data(lang=profile.language, profile=profile.model_dump(mode="json"))
        await show_main_menu(message, profile, state)
        with suppress(TelegramBadRequest):
            await message.delete()
    except ProfileNotFoundError:
        logger.info(f"Telegram user {message.from_user.id} started bot")
        await prompt_language_selection(message, state)


@cmd_router.message(Command(CommandName.info))
async def cmd_info(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile", {})
    profile = Profile.model_validate(profile_data) if profile_data else None
    lang = profile.language if profile else settings.DEFAULT_LANG
    await message.answer(
        translate(MessageText.info, lang).format(
            privacy_policy=settings.PRIVACY_POLICY,
            email=settings.OWNER_EMAIL or "unknown",
            owner_name=settings.OWNER_NAME or "Unknown owner",
            owner_address=settings.OWNER_ADDRESS or "Unknown address",
        ),
        disable_web_page_preview=True,
    )
    with suppress(TelegramBadRequest):
        await message.delete()


@cmd_router.message(Command(CommandName.help))
async def cmd_help(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile", {})
    profile = Profile.model_validate(profile_data) if profile_data else None
    lang = profile.language if profile else settings.DEFAULT_LANG
    faq_url = get_webapp_url("faq", lang) or settings.WEBAPP_PUBLIC_URL or ""
    await message.answer(
        translate(MessageText.help, lang).format(faq_url=faq_url),
        disable_web_page_preview=True,
    )
    with suppress(TelegramBadRequest):
        await message.delete()
