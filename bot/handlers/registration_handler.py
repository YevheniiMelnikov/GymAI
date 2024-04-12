import loguru
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.commands import bot_commands
from bot.keyboards import *
from bot.states import States
from common.functions import create_person, edit_person, get_person, set_data_and_next_state, show_main_menu, \
    validate_birth_date
from texts.text_manager import MessageText, translate

logger = loguru.logger
register_router = Router()


@register_router.message(States.language_choice, F.text)
async def set_language(message: Message, state: FSMContext, bot: Bot) -> None:
    if lang := codes.get(message.text):
        await bot.set_my_commands(bot_commands[lang])
        if await get_person(message.from_user.id):
            await edit_person(message.from_user.id, dict(language=lang))
            await show_main_menu(message, state, lang)
        else:
            await state.update_data(lang=lang)
            await message.answer(
                text=translate(MessageText.choose_account_type, lang=lang),
                reply_markup=choose_account_type(lang),
            )
            await state.set_state(States.account_type)
    else:
        await message.answer(translate(MessageText.invalid_content, lang="ua"))
        await message.delete()


@register_router.callback_query(States.account_type)
async def set_account_type(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await callback_query.answer(translate(MessageText.saved, lang=data["lang"]))
    await set_data_and_next_state(
        callback_query.message, state, States.short_name, dict(account_type=callback_query.data)
    )
    await callback_query.message.answer(translate(MessageText.choose_short_name, lang=data["lang"]))


@register_router.message(States.short_name, F.text)
async def set_short_name(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await set_data_and_next_state(message, state, States.password, dict(short_name=message.text))
    await message.answer(translate(MessageText.choose_password, lang=data["lang"]))


@register_router.message(States.password, F.text)
async def set_password(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await set_data_and_next_state(message, state, States.gender, dict(password=message.text))
    await message.answer(text=translate(MessageText.choose_gender), reply_markup=choose_gender(data["lang"]))


@register_router.callback_query(States.gender)
async def set_gender(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await callback_query.answer(translate(MessageText.saved, lang=data["lang"]))
    await set_data_and_next_state(callback_query.message, state, States.birth_date, dict(gender=callback_query.data))
    await callback_query.message.answer(text=translate(MessageText.choose_birth_date, lang=data["lang"]))


@register_router.message(States.birth_date, F.text)
async def set_birth_date_and_register(message: Message, state: FSMContext) -> None:
    if await validate_birth_date(message.text):
        await state.update_data(birth_date=message.text)
        data = await state.get_data()
        await create_person(
            dict(
                tg_user_id=message.from_user.id,
                short_name=data["short_name"],
                password=data["password"],
                status=data["account_type"],
                gender=data["gender"],
                birth_date=data["birth_date"],
                language=data["lang"],
            ),
        )
        logger.info(f"User {message.from_user.id} registered")
        await message.answer(text=translate(MessageText.registration_successful, lang=data["lang"]))
        await show_main_menu(message, state, data["lang"])
    else:
        data = await state.get_data()
        await message.answer(translate(MessageText.invalid_content, lang=data["lang"]))
