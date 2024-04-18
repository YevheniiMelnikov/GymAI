import loguru
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import language_choice
from bot.states import States
from common.user_service import user_service
from texts.text_manager import MessageText, translate

logger = loguru.logger
cmd_router = Router()


@cmd_router.message(Command("language"))
async def cmd_language(message: Message, state: FSMContext) -> None:
    if user := await user_service.current_user():  # TODO: implement
        lang = user.language
    else:
        lang = None

    await message.answer(
        text=translate(MessageText.choose_language, lang=lang) if lang else translate(MessageText.choose_language),
        reply_markup=language_choice(),
    )
    await state.set_state(States.language_choice)


@cmd_router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    logger.info(f"User {message.from_user.id} started bot")
    await state.clear()
    # if user_service.current_user():
    #     await user_service.log_out(token="token")  # TODO: implement
    await state.set_state(States.language_choice)
    await message.answer(text=translate(MessageText.choose_language), reply_markup=language_choice())


@cmd_router.message(Command("logout"))  # TODO: implement
async def cmd_logout(message: Message, state: FSMContext) -> None:
    pass


@cmd_router.message(Command("help"))  # TODO: implement
async def cmd_help(message: Message, state: FSMContext) -> None:
    pass
