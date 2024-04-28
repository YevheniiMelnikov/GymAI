import loguru
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.states import States
from common.utils import validate_birth_date
from texts.text_manager import MessageText, translate

logger = loguru.logger

questionnaire_router = Router()


@questionnaire_router.callback_query(States.gender)
async def gender(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await callback_query.answer(translate(MessageText.saved, lang=data["lang"]))
    await state.update_data(gender=callback_query.data)
    await state.set_state(States.birth_date)
    await callback_query.message.answer(text=translate(MessageText.birth_date, lang=data["lang"]))


@questionnaire_router.message(States.birth_date, F.text)
async def birth_date(message: Message, state: FSMContext) -> None:
    if validate_birth_date(message.text):
        await state.update_data(birth_date=message.text)
        await state.set_state(States.workout_goals)  # TODO: FIX VALIDATION
    else:
        data = await state.get_data()
        await message.answer(translate(MessageText.invalid_content, lang=data["lang"]))


@questionnaire_router.message(States.workout_goals, F.text)
async def training_goals(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(training_goals=message.text)
    await message.answer(translate(MessageText.weight, lang=data["lang"]))
    await state.set_state(States.weight)
