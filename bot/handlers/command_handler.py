import loguru
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import action_choice, language_choice
from bot.states import States
from common.user_service import user_service
from texts.text_manager import MessageText, translate

logger = loguru.logger
cmd_router = Router()


@cmd_router.message(Command("language"))
async def cmd_language(message: Message, state: FSMContext) -> None:
    profile = user_service.session.get_current_profile_by_tg_id(message.from_user.id)
    lang = profile.language if profile else None
    await message.answer(text=translate(MessageText.choose_language, lang=lang), reply_markup=language_choice())
    await state.set_state(States.language_choice)


@cmd_router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    logger.info(f"User {message.from_user.id} started bot")
    await state.clear()
    if profile := user_service.session.get_current_profile_by_tg_id(message.from_user.id):
        await user_service.log_out(message.from_user.id)
        await message.answer(text=translate(MessageText.start, lang=profile.language))
        await message.answer(
            text=translate(MessageText.choose_action, lang=profile.language),
            reply_markup=action_choice(profile.language),
        )
        await state.update_data(lang=profile.language)
        await message.delete()
        await state.set_state(States.action_choice)
        return

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
