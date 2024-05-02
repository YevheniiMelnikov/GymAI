import loguru
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import workout_experience_keyboard
from bot.states import States
from common.functions import show_main_menu, update_client_profile
from common.user_service import user_service
from common.utils import get_state_and_message, validate_birth_date
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
    await callback_query.message.delete()


@questionnaire_router.message(States.birth_date, F.text)
async def birth_date(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if validate_birth_date(message.text):
        await state.update_data(birth_date=message.text)
        await message.answer(translate(MessageText.workout_goals, lang=data["lang"]))
        await state.set_state(States.workout_goals)
    else:
        data = await state.get_data()
        await message.answer(message.text)
        await message.answer(translate(MessageText.invalid_content, lang=data["lang"]))
    await message.delete()


@questionnaire_router.message(States.workout_goals, F.text)
async def workout_goals(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(workout_goals=message.text)
    if data["edit_mode"]:
        await update_client_profile(message, state)
        return

    await message.answer(
        translate(MessageText.workout_experience, lang=data["lang"]),
        reply_markup=workout_experience_keyboard(data["lang"]),
    )
    await state.set_state(States.workout_experience)
    await message.delete()


@questionnaire_router.callback_query(States.workout_experience)
async def workout_experience(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await callback_query.answer(translate(MessageText.saved, lang=data["lang"]))
    await state.update_data(workout_experience=callback_query.data)
    if data["edit_mode"]:
        await update_client_profile(callback_query.message, state)
        return

    await callback_query.message.answer(translate(MessageText.weight, lang=data["lang"]))
    await state.set_state(States.weight)
    await callback_query.message.delete()


@questionnaire_router.message(States.weight, F.text)
async def weight(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not all(map(lambda x: x.isdigit(), message.text.split())):
        await message.answer(translate(MessageText.invalid_content, lang=data["lang"]))
        await state.set_state(States.weight)
        return

    await state.update_data(weight=message.text)
    if data["edit_mode"]:
        await update_client_profile(message, state)
        return

    await message.answer(translate(MessageText.health_notes, lang=data["lang"]))
    await state.set_state(States.health_notes)
    await message.delete()


@questionnaire_router.message(States.health_notes, F.text)
async def health_notes(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(health_notes=message.text)
    await message.answer(translate(MessageText.weight, lang=data["lang"]))
    await state.set_state(States.weight)
    await update_client_profile(message, state)


@questionnaire_router.callback_query(States.edit_client_profile)  # TODO: FIND BETTER SOLUTION
async def edit_client_profile(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile = user_service.storage.get_current_profile_by_tg_id(callback_query.from_user.id)
    if callback_query.data == "back":
        await state.set_state(States.main_menu)
        await show_main_menu(callback_query.message, profile, state)
        return

    state_to_set, message = get_state_and_message(callback_query.data, profile.language)
    await state.update_data(edit_mode=True)
    if state_to_set == States.workout_experience:
        await callback_query.message.answer(
            message, lang=profile.language, reply_markup=workout_experience_keyboard(profile.language)
        )
    else:
        await callback_query.message.answer(message, lang=profile.language)
    await state.set_state(state_to_set)
