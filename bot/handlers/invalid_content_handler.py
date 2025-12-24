from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.states import States
from bot.texts import MessageText, translate
from config.app_settings import settings

invalid_content_router = Router()


async def handle_invalid_content(message: Message, lang: str) -> None:
    await message.answer(translate(MessageText.invalid_content, lang))
    await message.delete()


HANDLED_STATES = [
    States.select_language,
    States.born_in,
    States.gender,
    States.workout_goals,
    States.weight,
    States.height,
    States.workout_experience,
    States.health_notes,
    States.diet_allergies,
    States.main_menu,
    States.profile_delete,
    States.program_edit,
]


async def invalid_data_handler(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await handle_invalid_content(message, data.get("lang", settings.DEFAULT_LANG))


for state_ in HANDLED_STATES:
    invalid_content_router.message(state_)(invalid_data_handler)
