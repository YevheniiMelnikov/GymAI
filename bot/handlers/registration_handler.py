from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import *
from bot.states import States
from bot.texts.text_manager import msg_text
from common.logger import logger
from core.cache_manager import CacheManager
from core.exceptions import EmailUnavailable, UsernameUnavailable
from common.settings import settings
from functions.menus import show_main_menu, show_my_profile_menu
from functions.profiles import check_assigned_clients, get_or_load_profile, register_user, sign_in
from functions.text_utils import validate_email, validate_password
from functions.utils import delete_messages, set_bot_commands
from services.profile_service import ProfileService
from services.user_service import user_service

register_router = Router()


@register_router.callback_query(States.select_language)
async def select_language(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    await delete_messages(state)
    lang_code = callback_query.data
    await set_bot_commands(lang_code)
    if profile := await get_or_load_profile(callback_query.from_user.id):
        await ProfileService.edit_profile(profile.id, {"language": lang_code})
        CacheManager.set_profile_info_by_key(callback_query.from_user.id, profile.id, "language", lang_code)
        profile.language = lang_code
        await show_main_menu(callback_query.message, profile, state)
    else:
        await state.update_data(lang=lang_code)
        await callback_query.message.answer(
            msg_text("select_action", lang_code),
            reply_markup=action_choice_kb(lang_code),
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
        username_message = await callback_query.message.answer(msg_text("username", data.get("lang")))
        await state.update_data(message_ids=[username_message.message_id], chat_id=callback_query.message.chat.id)
        await state.set_state(States.username)
    elif callback_query.data == "sign_up":
        await callback_query.message.answer(
            msg_text("choose_account_type", data.get("lang")),
            reply_markup=select_role_kb(data.get("lang")),
        )
        await state.set_state(States.account_type)

    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


@register_router.callback_query(States.account_type)
async def account_type(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await callback_query.answer(msg_text("saved", data.get("lang")))
    await state.update_data(account_type=callback_query.data)
    await state.set_state(States.username)
    username_message = await callback_query.message.answer(msg_text("username", data.get("lang")))
    await state.update_data(message_ids=[username_message.message_id])
    await callback_query.message.delete()


@register_router.message(States.username, F.text)
async def username(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await delete_messages(state)
    password_requirements_message = None
    if data.get("action") == "sign_up":
        if await ProfileService.get_profile_by_username(message.text):
            await state.set_state(States.username)
            await message.answer(msg_text("username_unavailable", data.get("lang")))
            return
        else:
            password_requirements_message = await message.answer(msg_text("password_requirements", data.get("lang")))
            await state.update_data(message_ids=[password_requirements_message.message_id])

    password_message = await message.answer(msg_text("password", data.get("lang", settings.DEFAULT_BOT_LANGUAGE)))
    await state.update_data(username=message.text, message_ids=[password_message.message_id])
    if password_requirements_message:
        await state.update_data(message_ids=[password_message.message_id, password_requirements_message.message_id])
    await state.set_state(States.password)
    await message.delete()


@register_router.message(States.password, F.text)
async def password(message: Message, state: FSMContext) -> None:
    await state.update_data(chat_id=message.chat.id)
    await delete_messages(state)
    data = await state.get_data()
    if data.get("action") == "sign_up":
        if not validate_password(message.text):
            await message.answer(msg_text("password_unsafe", data.get("lang")))
            await state.set_state(States.password)
        else:
            await state.update_data(password=message.text)
            password_retype_message = await message.answer(msg_text("password_retype", data.get("lang")))
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
        email_message = await message.answer(msg_text("email", data.get("lang")))
        await state.update_data(message_ids=[email_message.message_id])
        await state.set_state(States.email)
    else:
        password_mismatch_message = await message.answer(msg_text("password_mismatch", data.get("lang")))
        await state.update_data(message_ids=[password_mismatch_message.message_id])
        await state.set_state(States.password)
    await message.delete()


@register_router.message(States.email, F.text)
async def email(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await delete_messages(state)

    if not validate_email(message.text):
        await message.answer(msg_text("invalid_content", data.get("lang")))
        await message.delete()
        return

    await state.update_data(email=message.text)
    contract_info_message = await message.answer(
        msg_text("contract_info_message", data.get("lang")).format(
            public_offer=settings.PUBLIC_OFFER, privacy_policy=settings.PRIVACY_POLICY
        ),
        disable_web_page_preview=True,
    )
    await message.answer(msg_text("accept_policy", data.get("lang")), reply_markup=yes_no_kb(data.get("lang")))
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
        except UsernameUnavailable as e:
            logger.error(f"Username unavailable: {e.username}")
            await state.set_state(States.username)
            username_unavailable_message = await callback_query.message.answer(msg_text("username_unavailable", lang))
            await state.update_data(message_ids=[username_unavailable_message.message_id])
        except EmailUnavailable as e:
            logger.error(f"Email unavailable: {e.email}")
            email_unavailable_message = await callback_query.message.answer(msg_text("email_unavailable", lang))
            await state.update_data(message_ids=[email_unavailable_message.message_id])
            await state.set_state(States.email)
        finally:
            with suppress(TelegramBadRequest):
                await callback_query.message.delete()
    else:
        action_message = await callback_query.message.answer(
            msg_text("select_action", lang),
            reply_markup=action_choice_kb(lang),
        )
        await state.clear()
        await state.update_data(lang=lang, message_ids=[action_message.message_id])
        await state.set_state(States.action_choice)


@register_router.callback_query(States.profile_delete)
async def delete_profile_confirmation(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile = await get_or_load_profile(callback_query.from_user.id)
    lang = profile.language
    if callback_query.data == "yes":
        if profile.status == "coach":
            if await check_assigned_clients(profile.id):
                await callback_query.answer(msg_text("unable_to_delete_profile", lang))
                return
        auth_token = await user_service.get_user_token(profile.id)
        if await ProfileService.delete_profile(profile.id, auth_token):
            CacheManager.delete_profile(callback_query.from_user.id, profile.id)
            await callback_query.message.answer(msg_text("profile_deleted", profile.language))
            await callback_query.message.answer(
                msg_text("select_action", lang),
                reply_markup=action_choice_kb(lang),
            )
            await callback_query.message.delete()
            await state.clear()
            await state.update_data(lang)
            await state.set_state(States.action_choice)
        else:
            await callback_query.message.answer(msg_text("unexpected_error", lang))
    else:
        await show_my_profile_menu(callback_query, profile, state)
