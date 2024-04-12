from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.states import States
from texts.text_manager import MessageText, translate

invalid_content_router = Router()


@invalid_content_router.message(States.language_choice)
async def invalid_language(message: Message) -> None:
    await message.answer(translate(MessageText.invalid_content, lang="ua"))
    await message.delete()


@invalid_content_router.message(States.short_name)
async def invalid_short_name(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await message.answer(translate(MessageText.invalid_content, lang=data["lang"]))
    await message.delete()


@invalid_content_router.message(States.password)
async def invalid_password(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await message.answer(translate(MessageText.invalid_content, lang=data["lang"]))
    await message.delete()


@invalid_content_router.message(States.birth_date)
async def invalid_birth_date(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await message.answer(translate(MessageText.invalid_content, lang=data["lang"]))
    await message.delete()


@invalid_content_router.message(States.account_type)
async def invalid_account_type(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await message.answer(translate(MessageText.invalid_content, lang=data["lang"]))
    await message.delete()


@invalid_content_router.message(States.gender)
async def invalid_gender(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await message.answer(translate(MessageText.invalid_content, lang=data["lang"]))
    await message.delete()
