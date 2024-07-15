from contextlib import suppress

import loguru
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import *
from bot.states import States
from common.exceptions import EmailUnavailable, UsernameUnavailable
from common.functions.menus import show_main_menu
from common.functions.profiles import register_user, sign_in
from common.functions.text_utils import validate_email, validate_password
from common.functions.utils import set_bot_commands
from common.user_service import user_service
from texts.text_manager import MessageText, translate

logger = loguru.logger
register_router = Router()


@register_router.callback_query(States.language_choice)
async def language_choice(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    lang_code = callback_query.data
    await set_bot_commands(lang_code)
    if profile := user_service.storage.get_current_profile(callback_query.from_user.id):
        token = user_service.storage.get_profile_info_by_key(callback_query.from_user.id, profile.id, "auth_token")
        await user_service.edit_profile(profile.id, {"language": lang_code}, token)
        user_service.storage.set_profile_info_by_key(
            str(callback_query.from_user.id), profile.id, "language", lang_code
        )
        profile.language = lang_code
        await show_main_menu(callback_query.message, profile, state)
    else:
        await state.update_data(lang=lang_code)
        await callback_query.message.answer(
            text=translate(MessageText.choose_action, lang=lang_code),
            reply_markup=action_choice_keyboard(lang_code),
        )
        await state.set_state(States.action_choice)

    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


@register_router.callback_query(States.action_choice)
async def action_choice(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    data = await state.get_data()
    await state.update_data(action=callback_query.data)

    if callback_query.data == "sign_in":
        await callback_query.message.answer(translate(MessageText.username, lang=data.get("lang")))
        await state.set_state(States.username)
    elif callback_query.data == "sign_up":
        await callback_query.message.answer(
            translate(MessageText.choose_account_type, lang=data.get("lang")),
            reply_markup=choose_account_type(data.get("lang")),
        )
        await state.set_state(States.account_type)

    await callback_query.message.delete()


@register_router.callback_query(States.account_type)
async def account_type(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await callback_query.answer(translate(MessageText.saved, lang=data.get("lang")))
    await state.update_data(account_type=callback_query.data)
    await state.set_state(States.username)
    await callback_query.message.answer(translate(MessageText.username, lang=data.get("lang")))
    await callback_query.message.delete()


@register_router.message(States.username, F.text)
async def username(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(username=message.text)
    await state.set_state(States.password)
    await message.answer(translate(MessageText.password, lang=data.get("lang", "ua")))
    if data.get("action") == "sign_up":
        await message.answer(text=translate(MessageText.password_requirements, lang=data.get("lang")))
    await message.delete()


@register_router.message(States.password, F.text)
async def password(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("action") == "sign_up":
        if not validate_password(message.text):
            await message.answer(text=translate(MessageText.password_unsafe, lang=data.get("lang")))
            await state.set_state(States.password)
        else:
            await state.update_data(password=message.text)
            await message.answer(text=translate(MessageText.password_retype, lang=data.get("lang")))
            await state.set_state(States.password_retype)
        await message.delete()

    else:
        await sign_in(message, state, data)


@register_router.message(States.password_retype, F.text)
async def password_retype(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if message.text == data["password"]:
        await state.set_state(States.email)
        await message.answer(text=translate(MessageText.email, lang=data.get("lang")))
    else:
        await state.set_state(States.password)
        await message.answer(text=translate(MessageText.password_mismatch, lang=data.get("lang")))
    await message.delete()


@register_router.message(States.email, F.text)
async def email(message: Message, state: FSMContext) -> None:
    data = await state.get_data()

    if not validate_email(message.text):
        await message.answer(text=translate(MessageText.invalid_content, lang=data.get("lang")))
        await message.delete()
        return

    try:
        await register_user(message, state, data)
    except UsernameUnavailable:
        await state.set_state(States.username)
        await message.answer(text=translate(MessageText.username_unavailable, lang=data.get("lang")))
    except EmailUnavailable:
        await message.answer(text=translate(MessageText.email_unavailable, lang=data.get("lang")))
    finally:
        with suppress(TelegramBadRequest):
            await message.delete()
