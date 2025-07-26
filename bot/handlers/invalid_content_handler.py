from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.states import States
from bot.texts.text_manager import msg_text
from config.app_settings import settings

invalid_content_router = Router()


async def handle_invalid_content(message: Message, lang: str) -> None:
    await message.answer(msg_text("invalid_content", lang))
    await message.delete()


HANDLED_STATES = [
    States.select_language,
    States.born_in,
    States.account_type,
    States.gender,
    States.workout_goals,
    States.weight,
    States.workout_experience,
    States.health_notes,
    States.name,
    States.payment_choice,
    States.select_workout,
    States.work_experience,
    States.additional_info,
    States.payment_details,
    States.profile_photo,
    States.contact_client,
    States.main_menu,
    States.profile_delete,
    States.gift,
    States.program_edit,
]


async def invalid_data_handler(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await handle_invalid_content(message, data.get("lang", settings.DEFAULT_LANG))


for state_ in HANDLED_STATES:
    invalid_content_router.message(state_)(invalid_data_handler)
