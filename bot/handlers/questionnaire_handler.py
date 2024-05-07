import loguru
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import workout_experience_keyboard
from bot.states import States
from common.functions import show_main_menu, update_user_info
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
    if data.get("edit_mode"):
        await update_user_info(message, state, "client")
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
    if data.get("edit_mode"):
        await update_user_info(callback_query.message, state, "client")
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
    if data.get("edit_mode"):
        await update_user_info(message, state, "client")
        return

    await message.answer(translate(MessageText.health_notes, lang=data["lang"]))
    await state.set_state(States.health_notes)
    await message.delete()


@questionnaire_router.message(States.health_notes, F.text)
async def health_notes(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(health_notes=message.text)
    await message.answer(translate(MessageText.weight, lang=data["lang"]))
    await update_user_info(message, state, "client")


@questionnaire_router.message(States.name, F.text)
async def name(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(name=message.text)
    await message.answer(translate(MessageText.work_experience, lang=data["lang"]))
    await state.set_state(States.work_experience)
    await message.delete()


@questionnaire_router.message(States.work_experience, F.text)
async def work_experience(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not all(map(lambda x: x.isdigit(), message.text.split())):
        await message.answer(translate(MessageText.invalid_content, lang=data["lang"]))
        await message.answer(translate(MessageText.work_experience, lang=data["lang"]))
        await state.set_state(States.work_experience)
        return

    await state.update_data(work_experience=message.text)
    if data.get("edit_mode"):
        await update_user_info(message, state, "coach")
        return

    await message.answer(translate(MessageText.additional_info, lang=data["lang"]))
    await state.set_state(States.additional_info)
    await message.delete()


@questionnaire_router.message(States.additional_info, F.text)
async def additional_info(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(additional_info=message.text)
    if data.get("edit_mode"):
        await update_user_info(message, state, "coach")
        return

    await message.answer(translate(MessageText.payment_details, lang=data["lang"]))
    await state.set_state(States.payment_details)
    await message.delete()


@questionnaire_router.message(States.payment_details, F.text)
async def payment_details(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    card_number = message.text.replace(" ", "")
    if not all(map(lambda x: x.isdigit(), card_number)) or len(card_number) != 16:
        await message.answer(translate(MessageText.invalid_content, lang=data["lang"]))
        await state.set_state(States.payment_details)
        return

    await state.update_data(payment_details=message.text.replace(" ", ""))
    await update_user_info(message, state, "coach")


@questionnaire_router.callback_query(States.edit_profile)
async def update_profile(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    await state.update_data(lang=profile.language)
    if callback_query.data == "back":
        await state.set_state(States.main_menu)
        await show_main_menu(callback_query.message, profile, state)
        return

    state_to_set, message = get_state_and_message(callback_query.data, profile.language)
    await state.update_data(edit_mode=True)
    reply_markup = workout_experience_keyboard(profile.language) if state_to_set == States.workout_experience else None
    await callback_query.message.answer(message, lang=profile.language, reply_markup=reply_markup)
    await state.set_state(state_to_set)
