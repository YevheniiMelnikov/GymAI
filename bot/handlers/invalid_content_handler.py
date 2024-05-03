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


@invalid_content_router.message(States.username)
async def invalid_username(message: Message, state: FSMContext) -> None:
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


@invalid_content_router.message(States.workout_goals)
async def invalid_workout_goals(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await message.answer(translate(MessageText.invalid_content, lang=data["lang"]))
    await message.delete()


@invalid_content_router.message(States.weight)
async def invalid_weight(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await message.answer(translate(MessageText.invalid_content, lang=data["lang"]))
    await message.delete()


@invalid_content_router.message(States.workout_experience)
async def invalid_workout_experience(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await message.answer(translate(MessageText.invalid_content, lang=data["lang"]))
    await message.delete()


@invalid_content_router.message(States.health_notes)
async def invalid_health_notes(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await message.answer(translate(MessageText.invalid_content, lang=data["lang"]))
    await message.delete()


@invalid_content_router.message(States.name)
async def invalid_name(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await message.answer(translate(MessageText.invalid_content, lang=data["lang"]))
    await message.delete()


@invalid_content_router.message(States.work_experience)
async def invalid_work_experience(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await message.answer(translate(MessageText.invalid_content, lang=data["lang"]))
    await message.delete()


@invalid_content_router.message(States.additional_info)
async def invalid_additional_info(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await message.answer(translate(MessageText.invalid_content, lang=data["lang"]))
    await message.delete()


@invalid_content_router.message(States.payment_details)
async def invalid_payment_details(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await message.answer(translate(MessageText.invalid_content, lang=data["lang"]))
    await message.delete()
