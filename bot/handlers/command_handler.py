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
    profile = user_service.session.current_profile(message.from_user.id)
    lang = profile.language if profile else None
    text = translate(MessageText.choose_language, lang=lang) if lang else translate(MessageText.choose_language)
    await message.answer(text=text, reply_markup=language_choice())
    await state.set_state(States.language_choice)


@cmd_router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    logger.info(f"User {message.from_user.id} started bot")
    await state.clear()
    await user_service.log_out(message.from_user.id)
    await state.set_state(States.language_choice)
    await message.answer(text=translate(MessageText.choose_language), reply_markup=language_choice())


@cmd_router.message(Command("logout"))
async def cmd_logout(message: Message, state: FSMContext) -> None:
    await state.clear()
    await user_service.log_out(message.from_user.id)
    await message.answer(text=translate(MessageText.logout))


@cmd_router.message(Command("help"))  # TODO: implement
async def cmd_help(message: Message, state: FSMContext) -> None:
    pass
