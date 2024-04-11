import loguru
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import language_choice
from bot.states import States
from common.functions import get_person, show_main_menu
from texts.text_manager import MessageText, translate

logger = loguru.logger
cmd_router = Router()


@cmd_router.message(Command("language"))
async def cmd_language(message: Message, state: FSMContext) -> None:
    person = await get_person(message.from_user.id)
    if person:
        await message.answer(
            text=translate(MessageText.choose_language, lang=person.language), reply_markup=language_choice()
        )
        await state.set_state(States.language_choice)


@cmd_router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    logger.info(f"User {message.from_user.id} started bot")
    await state.clear()
    person = await get_person(message.from_user.id)
    if person:
        if not person.language:
            await state.set_state(States.language_choice)
            await message.answer(text=translate(MessageText.choose_language), reply_markup=language_choice())
        else:
            await show_main_menu(message, state)
    else:
        await state.set_state(States.language_choice)
        await message.answer(text=translate(MessageText.choose_language), reply_markup=language_choice())


@cmd_router.message(Command("logout"))
async def cmd_logout(message: Message, state: FSMContext) -> None:
    pass


@cmd_router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext) -> None:
    pass
