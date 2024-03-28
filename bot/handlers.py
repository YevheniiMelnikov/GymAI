from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import language_choice, main_menu_keyboard
from bot.states import States
from common.functions import get_person_by_id, add_user_to_db, edit_person
from texts.text_manager import translate, MessageText

start_router = Router()


@start_router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    person = await get_person_by_id(message.from_user.id)
    if person:
        await state.set_state(States.main_menu)
        await message.answer(
            text=translate(MessageText.start, lang=person.language),
            reply_markup=main_menu_keyboard(person.language),
        )
    else:
        await message.answer(text=translate(MessageText.choose_language), reply_markup=language_choice())
        await state.set_state(States.language_choice)


@start_router.message(Command("language"))
async def cmd_language(message: Message, state: FSMContext) -> None:
    await message.answer(text=translate(MessageText.choose_language), reply_markup=language_choice())
    await state.set_state(States.language_choice)


@start_router.message(States.language_choice)
async def create_user(message: Message, state: FSMContext) -> None:
    codes = {"Українська 🇺🇦": "ua", "English 🇬🇧": "eng", "Русский 🇷🇺": "ru"}
    lang_code = codes.get(message.text)

    if lang_code:
        person = await get_person_by_id(message.from_user.id)
        if person:
            await edit_person(message.from_user.id, {"language": lang_code})
        else:
            await add_user_to_db(user_id=message.from_user.id, lang=lang_code)
        await state.set_state(States.main_menu)
        await message.answer(
            text=translate(MessageText.start, lang=lang_code),
            reply_markup=main_menu_keyboard(lang_code),
        )
    else:
        await message.answer(text=translate(MessageText.choose_language), reply_markup=language_choice())
