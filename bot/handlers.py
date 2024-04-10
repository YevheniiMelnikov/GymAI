import loguru
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import codes, language_choice, main_menu_keyboard
from bot.states import States
from common.functions import create_person, edit_person, get_person
from texts.text_manager import MessageText, translate

logger = loguru.logger
main_router = Router()


@main_router.message(Command("language"))
async def cmd_language(message: Message, state: FSMContext) -> None:
    await message.answer(text=translate(MessageText.choose_language), reply_markup=language_choice())
    await state.set_state(States.language_choice)


@main_router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    logger.info(f"User {message.from_user.id} started bot")
    await state.clear()
    if person := await get_person(message.from_user.id):
        await state.set_state(States.main_menu)
        await message.answer(
            text=translate(MessageText.start, lang="ru"),  # TODO: PASS PERSON.LANGUAGE
            reply_markup=main_menu_keyboard(person.language),
        )
    else:
        await message.answer(text=translate(MessageText.choose_language), reply_markup=language_choice())
        await state.set_state(States.language_choice)


@main_router.message(States.language_choice)
async def create_user(message: Message, state: FSMContext) -> None:
    if lang_code := codes.get(message.text):
        if await get_person(message.from_user.id):
            await edit_person(message.from_user.id, {"language": lang_code})
        else:
            await create_person(
                dict(tg_user_id=message.from_user.id, short_name="username", password="password", language=lang_code)
            )  # TODO: ADD EXTRA STEPS
        await state.set_state(States.main_menu)
        await message.answer(
            text=translate(MessageText.start, lang=lang_code),
            reply_markup=main_menu_keyboard(lang_code),
        )
    else:
        await message.answer(text=translate(MessageText.choose_language), reply_markup=language_choice())
