from contextlib import suppress

import loguru
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import *
from bot.states import States
from common.exceptions import UsernameUnavailable
from common.functions import register_user, set_bot_commands, show_main_menu, sign_in
from common.user_service import user_service
from common.utils import validate_email, validate_password
from texts.text_manager import MessageText, translate

logger = loguru.logger
register_router = Router()


@register_router.message(States.language_choice, F.text)
async def language(message: Message, state: FSMContext) -> None:
    lang_code = codes.get(message.text)
    if not lang_code:
        await message.answer(translate(MessageText.invalid_content))
        await message.delete()
        return

    await set_bot_commands(lang_code)
    if profile := user_service.storage.get_current_profile_by_tg_id(message.from_user.id):
        token = user_service.storage.get_profile_info_by_key(message.from_user.id, profile.id, "auth_token")
        if await user_service.edit_profile(profile.id, {"language": lang_code}, token):
            user_service.storage.set_profile_info_by_key(message.from_user.id, profile.id, "language", lang_code)
            profile.language = lang_code
            await show_main_menu(message, profile, state)
        else:
            await message.answer(text=translate(MessageText.unexpected_error, lang=lang_code))
    else:
        await state.update_data(lang=lang_code)
        await message.answer(
            text=translate(MessageText.choose_action, lang=lang_code),
            reply_markup=action_choice_keyboard(lang_code),
        )
        await state.set_state(States.action_choice)

    with suppress(TelegramBadRequest):
        await message.delete()


@register_router.callback_query(States.action_choice)
async def action(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(action=callback_query.data)

    if callback_query.data == "sign_in":
        await callback_query.message.answer(translate(MessageText.username, lang=data["lang"]))
        await state.set_state(States.username)
    elif callback_query.data == "sign_up":
        await callback_query.message.answer(
            translate(MessageText.choose_account_type, lang=data["lang"]),
            reply_markup=choose_account_type(data["lang"]),
        )
        await state.set_state(States.account_type)

    await callback_query.message.delete()


@register_router.callback_query(States.account_type)
async def account_type(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await callback_query.answer(translate(MessageText.saved, lang=data["lang"]))
    await state.update_data(account_type=callback_query.data)
    await state.set_state(States.username)
    await callback_query.message.answer(translate(MessageText.username, lang=data["lang"]))
    await callback_query.message.delete()


@register_router.message(States.username, F.text)
async def username(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(username=message.text)
    await state.set_state(States.password)
    await message.answer(translate(MessageText.password, lang=data["lang"]))
    if data.get("action") == "sign_up":
        await message.answer(text=translate(MessageText.password_requirements, lang=data["lang"]))
    await message.delete()


@register_router.message(States.password, F.text)
async def password(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("action") == "sign_up":
        if not validate_password(message.text):
            await message.answer(text=translate(MessageText.password_unsafe, lang=data["lang"]))
            await state.set_state(States.password)
        else:
            await state.update_data(password=message.text)
            await message.answer(text=translate(MessageText.password_retype, lang=data["lang"]))
            await state.set_state(States.password_retype)
        await message.delete()

    else:
        await sign_in(message, state, data)


@register_router.message(States.password_retype, F.text)
async def password_retype(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if message.text == data["password"]:
        await state.set_state(States.email)
        await message.answer(text=translate(MessageText.email, lang=data["lang"]))
    else:
        await state.set_state(States.password)
        await message.answer(text=translate(MessageText.password_mismatch, lang=data["lang"]))
    await message.delete()


@register_router.message(States.email, F.text)
async def email(message: Message, state: FSMContext) -> None:
    data = await state.get_data()

    if not validate_email(message.text):
        await message.answer(text=translate(MessageText.invalid_content, lang=data["lang"]))
        await message.delete()
        return

    try:
        await register_user(message, state, data)
    except UsernameUnavailable:
        await state.set_state(States.username)
        await message.answer(text=translate(MessageText.username_unavailable, lang=data["lang"]))
    finally:
        with suppress(TelegramBadRequest):
            await message.delete()
