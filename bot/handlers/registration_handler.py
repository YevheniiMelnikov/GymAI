import os
from contextlib import suppress

import loguru
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import *
from bot.states import States
from common.exceptions import EmailUnavailable, UsernameUnavailable
from common.functions.menus import show_main_menu, show_my_profile_menu
from common.functions.profiles import register_user, sign_in, check_assigned_clients
from common.functions.text_utils import validate_email, validate_password
from common.functions.utils import set_bot_commands, delete_messages
from common.user_service import user_service
from texts.text_manager import MessageText, translate

logger = loguru.logger
register_router = Router()


@register_router.callback_query(States.language_choice)
async def language_choice(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    await delete_messages(state)
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
    await delete_messages(state)
    data = await state.get_data()
    await state.update_data(action=callback_query.data)

    if callback_query.data == "sign_in":
        username_message = await callback_query.message.answer(translate(MessageText.username, lang=data.get("lang")))
        await state.update_data(message_ids=[username_message.message_id])
        await state.set_state(States.username)
    elif callback_query.data == "sign_up":
        await callback_query.message.answer(
            translate(MessageText.choose_account_type, lang=data.get("lang")),
            reply_markup=choose_account_type(data.get("lang")),
        )
        await state.set_state(States.account_type)

    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


@register_router.callback_query(States.account_type)
async def account_type(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await callback_query.answer(translate(MessageText.saved, lang=data.get("lang")))
    await state.update_data(account_type=callback_query.data)
    await state.set_state(States.username)
    username_message = await callback_query.message.answer(translate(MessageText.username, lang=data.get("lang")))
    await state.update_data(message_ids=[username_message.message_id])
    await callback_query.message.delete()


@register_router.message(States.username, F.text)
async def username(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await delete_messages(state)
    if data.get("action") == "sign_up":
        if await user_service.get_profile_by_username(message.text):
            await state.set_state(States.username)
            await message.answer(text=translate(MessageText.username_unavailable, lang=data.get("lang")))
            return
        else:
            password_requirements_message = await message.answer(
                text=translate(MessageText.password_requirements, lang=data.get("lang"))
            )
            await state.update_data(message_ids=[password_requirements_message.message_id])
            await delete_messages(state)

    password_message = await message.answer(translate(MessageText.password, lang=data.get("lang", "ua")))
    await state.update_data(username=message.text, message_ids=[password_message.message_id])
    await state.set_state(States.password)
    await message.delete()


@register_router.message(States.password, F.text)
async def password(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    if data.get("action") == "sign_up":
        if not validate_password(message.text):
            await message.answer(text=translate(MessageText.password_unsafe, lang=data.get("lang")))
            await state.set_state(States.password)
        else:
            await state.update_data(password=message.text)
            password_retype_message = await message.answer(
                text=translate(MessageText.password_retype, lang=data.get("lang"))
            )
            await state.update_data(message_ids=[password_retype_message.message_id])
            await state.set_state(States.password_retype)
        await message.delete()

    else:
        await sign_in(message, state, data)


@register_router.message(States.password_retype, F.text)
async def password_retype(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await delete_messages(state)
    if message.text == data["password"]:
        email_message = await message.answer(text=translate(MessageText.email, lang=data.get("lang")))
        await state.update_data(message_ids=[email_message.message_id])
        await state.set_state(States.email)
    else:
        password_mismatch_message = await message.answer(
            text=translate(MessageText.password_mismatch, lang=data.get("lang"))
        )
        await state.update_data(message_ids=[password_mismatch_message.message_id])
        await state.set_state(States.password)
    await message.delete()


@register_router.message(States.email, F.text)
async def email(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await delete_messages(state)

    if not validate_email(message.text):
        await message.answer(text=translate(MessageText.invalid_content, lang=data.get("lang")))
        await message.delete()
        return

    await state.update_data(email=message.text)
    public_offer = os.getenv("PUBLIC_OFFER")
    privacy_policy = os.getenv("PRIVACY_POLICY")
    contract_info_message = await message.answer(
        translate(MessageText.contract_info_message, data.get("lang")).format(
            public_offer=public_offer, privacy_policy=privacy_policy
        ),
        disable_web_page_preview=True,
    )
    await message.answer(
        translate(MessageText.accept_policy, lang=data.get("lang")), reply_markup=yes_no(data.get("lang"))
    )
    await state.update_data(message_ids=[contract_info_message.message_id])
    await message.delete()
    await state.set_state(States.accept_policy)


@register_router.callback_query(States.accept_policy)
async def accept_policy(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang")
    await delete_messages(state)

    if callback_query.data == "yes":
        try:
            await register_user(callback_query, state, data)
        except UsernameUnavailable:
            await state.set_state(States.username)
            username_unavailable_message = await callback_query.message.answer(
                text=translate(MessageText.username_unavailable, lang=lang)
            )
            await state.update_data(message_ids=[username_unavailable_message.message_id])
        except EmailUnavailable:
            email_unavailable_message = await callback_query.message.answer(
                text=translate(MessageText.email_unavailable, lang=lang)
            )
            await state.update_data(message_ids=[email_unavailable_message.message_id])
            await state.set_state(States.email)
        finally:
            with suppress(TelegramBadRequest):
                await callback_query.message.delete()
    else:
        action_message = await callback_query.message.answer(
            text=translate(MessageText.choose_action, lang=lang),
            reply_markup=action_choice_keyboard(lang_code=lang),
        )
        await state.clear()
        await state.update_data(lang=lang, message_ids=[action_message.message_id])
        await state.set_state(States.action_choice)


@register_router.callback_query(States.profile_delete)
async def delete_profile_confirmation(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    lang = profile.language
    if callback_query.data == "yes":
        if profile.status == "coach":
            if await check_assigned_clients(profile.id):
                await callback_query.answer(translate(MessageText.unable_to_delete_profile, lang=lang))
                return
        token = user_service.storage.get_profile_info_by_key(callback_query.from_user.id, profile.id, "auth_token")
        if await user_service.delete_profile(callback_query.from_user.id, profile.id, token):
            await callback_query.message.answer(translate(MessageText.profile_deleted, profile.language))
            await callback_query.message.answer(
                text=translate(MessageText.choose_action, lang=lang),
                reply_markup=action_choice_keyboard(lang_code=lang),
            )
            await callback_query.message.delete()
            await state.clear()
            await state.update_data(lang=lang)
            await state.set_state(States.action_choice)
        else:
            await callback_query.message.answer(translate(MessageText.unexpected_error, lang=lang))
    else:
        await show_my_profile_menu(callback_query, profile, state)
