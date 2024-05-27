from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.states import States
from texts.text_manager import MessageText, translate

invalid_content_router = Router()


async def handle_invalid_content(message: Message, lang: str) -> None:
    await message.answer(translate(MessageText.invalid_content, lang=lang))
    await message.delete()


@invalid_content_router.message(States.language_choice)
async def invalid_language(message: Message) -> None:
    await handle_invalid_content(message, "ua")


@invalid_content_router.message(States.username)
@invalid_content_router.message(States.password)
@invalid_content_router.message(States.birth_date)
@invalid_content_router.message(States.account_type)
@invalid_content_router.message(States.gender)
@invalid_content_router.message(States.workout_goals)
@invalid_content_router.message(States.weight)
@invalid_content_router.message(States.workout_experience)
@invalid_content_router.message(States.health_notes)
@invalid_content_router.message(States.name)
@invalid_content_router.message(States.payment_choice)
@invalid_content_router.message(States.select_program_type)
@invalid_content_router.message(States.work_experience)
@invalid_content_router.message(States.additional_info)
@invalid_content_router.message(States.payment_details)
@invalid_content_router.message(States.profile_photo, F.text)
@invalid_content_router.message(States.contact_client)
@invalid_content_router.message(States.main_menu)
async def invalid_data_handler(message: Message, state: FSMContext) -> None:  # TODO: FIND BETTER SOLUTION
    data = await state.get_data()
    await handle_invalid_content(message, data.get("lang", "ua"))
