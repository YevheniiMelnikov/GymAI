import loguru
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.commands import bot_commands
from bot.keyboards import *
from bot.states import States
from common.functions import show_main_menu, validate_email
from common.user_service import user_service
from texts.text_manager import MessageText, translate

logger = loguru.logger
register_router = Router()


@register_router.message(States.language_choice, F.text)
async def language(message: Message, state: FSMContext, bot: Bot) -> None:
    if lang := codes.get(message.text):
        await bot.set_my_commands(bot_commands[lang])
        if person := await user_service.current_person():
            await user_service.edit_person(person.id, dict(language=lang))
            await show_main_menu(message, state, lang)
            await message.delete()
        else:
            await state.update_data(lang=lang)
            await message.answer(
                text=translate(MessageText.choose_action, lang=lang),
                reply_markup=action_choice(lang),
            )
            await message.delete()
            await state.set_state(States.action_choice)
    else:
        await message.answer(translate(MessageText.invalid_content, lang="ua"))
        await message.delete()


@register_router.callback_query(States.action_choice)
async def action(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(action=callback_query.data)
    if callback_query.data == "sign_in":
        await state.set_state(States.username)
        await callback_query.message.answer(translate(MessageText.username, lang=data["lang"]))
    elif callback_query.data == "sign_up":
        await state.set_state(States.account_type)
        await callback_query.message.answer(
            translate(MessageText.choose_account_type, lang=data["lang"]),
            reply_markup=choose_account_type(data["lang"]),
        )
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
    await message.delete()


@register_router.message(States.password, F.text)
async def password(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(password=message.text)
    if data["action"] == "sign_in":
        if await user_service.sign_in(username=data["username"], password=message.text):
            await message.answer(text=translate(MessageText.signed_in, lang=data["lang"]))
            await show_main_menu(message, state, data["lang"])
            await message.delete()
        else:
            await message.answer(text=translate(MessageText.invalid_credentials, lang=data["lang"]))
            await state.set_state(States.username)
            await message.answer(text=translate(MessageText.username, lang=data["lang"]))
            await message.delete()
    elif data["action"] == "sign_up":
        await state.set_state(States.password_retype)
        await message.answer(text=translate(MessageText.password_retype, lang=data["lang"]))
        await message.delete()


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
    if validate_email(message.text):
        await state.update_data(email=message.text)
        if await user_service.sign_up(dict(username=data["username"], password=data["password"], email=message.text)):
            logger.info(f"User {message.from_user.id} registered")
            await message.answer(text=translate(MessageText.registration_successful, lang=data["lang"]))
            await show_main_menu(message, state, data["lang"])
            await state.clear()
        else:
            await message.answer(text=translate(MessageText.unexpected_error, lang=data["lang"]))
            await state.clear()
            await state.set_state(States.username)
            await message.answer(text=translate(MessageText.username, lang=data["lang"]))
        await message.delete()

    else:
        await state.set_state(States.email)
        await message.answer(text=translate(MessageText.invalid_content, lang=data["lang"]))
