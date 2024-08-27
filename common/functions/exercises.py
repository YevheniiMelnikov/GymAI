import os
from contextlib import suppress
from dataclasses import asdict

import loguru
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import program_edit_kb, program_manage_menu
from bot.states import States
from common.file_manager import gif_manager
from common.functions.text_utils import format_program, get_translated_week_day
from common.functions.utils import delete_messages
from common.models import Exercise
from common.user_service import user_service
from texts.exercises import exercise_dict
from texts.text_manager import MessageText, translate

bot = Bot(os.environ.get("BOT_TOKEN"))
logger = loguru.logger


async def save_exercise(state: FSMContext, exercise: Exercise, input_data: Message | CallbackQuery) -> None:
    data = await state.get_data()
    await delete_messages(state)
    profile = user_service.storage.get_current_profile(input_data.from_user.id)
    day_index = data.get("day_index", 0)
    exercises = data.get("exercises", {})
    client_id = data.get("client_id")

    if data.get("subscription"):
        days = data.get("days")
        current_day = days[day_index]
        day = get_translated_week_day(profile.language, current_day).lower()

        if str(day_index) not in exercises:
            exercises[str(day_index)] = [asdict(exercise)]
        else:
            if not any(ex["name"] == exercise.name for ex in exercises[str(day_index)]):
                exercises[str(day_index)].append(asdict(exercise))
        subscription_data = user_service.storage.get_subscription(client_id)
        split_number = len(subscription_data.workout_days)
        program = await format_program({days[day_index]: exercises[str(day_index)]}, days[day_index])
    else:
        day = day_index + 1
        if str(day_index) not in exercises:
            exercises[str(day_index)] = [asdict(exercise)]
        else:
            if not any(ex["name"] == exercise.name for ex in exercises[str(day_index)]):
                exercises[str(day_index)].append(asdict(exercise))
        program_data = user_service.storage.get_program(client_id)
        split_number = program_data.split_number
        program = await format_program({str(day_index): exercises[str(day_index)]}, day_index)

    exercise_msg = await (input_data.answer if isinstance(input_data, Message) else input_data.message.answer)(
        translate(MessageText.enter_exercise, profile.language)
    )
    program_msg = await exercise_msg.answer(
        text=translate(MessageText.program_page, profile.language).format(program=program, day=day),
        reply_markup=program_manage_menu(profile.language),
        disable_web_page_preview=True,
    )

    await state.update_data(
        chat_id=input_data.chat.id if isinstance(input_data, Message) else input_data.message.chat.id,
        message_ids=[exercise_msg.message_id, program_msg.message_id],
        exercises=exercises,
        day_index=day_index,
        split=split_number,
    )
    await state.set_state(States.program_manage)


async def find_exercise_gif(exercise: str) -> str | None:
    try:
        exercise = exercise.lower()
        for filename, synonyms in exercise_dict.items():
            if exercise in (syn.lower() for syn in synonyms):
                cached_filename = user_service.storage.get_exercise_gif(exercise)
                if cached_filename:
                    return f"https://storage.googleapis.com/{gif_manager.bucket_name}/{cached_filename}"

                blobs = list(gif_manager.bucket.list_blobs(prefix=filename))
                if blobs:
                    matching_blob = blobs[0]
                    if matching_blob.exists():
                        file_url = f"https://storage.googleapis.com/{gif_manager.bucket_name}/{matching_blob.name}"
                        user_service.storage.cache_gif_filename(exercise, matching_blob.name)
                        return file_url

    except Exception as e:
        logger.error(f"Failed to find gif for exercise {exercise}: {e}")

    logger.info(f"No matching file found for exercise: {exercise}")
    return None


async def update_exercise_data(message: Message, state: FSMContext, lang: str, updated_option: dict) -> None:
    data = await state.get_data()
    exercises = data.get("exercises", {})
    day_index = str(data.get("day_index"))
    exercise_index = data.get("exercise_index", 0)
    selected_exercise = exercises[day_index][exercise_index]
    updated_key = list(updated_option.keys())[0]
    updated_value = list(updated_option.values())[0]
    selected_exercise[updated_key] = updated_value
    exercises[day_index][exercise_index] = selected_exercise
    await state.update_data(exercises=exercises)
    await state.set_state(States.program_edit)
    await message.answer(translate(MessageText.continue_editing, lang), reply_markup=program_edit_kb(lang))
    await message.delete()


async def edit_subscription_exercises(callback_query: CallbackQuery, state: FSMContext, day_index: int) -> None:
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    client_id = callback_query.data.split("_")[1]
    day = callback_query.data.split("_")[2]
    subscription = user_service.storage.get_subscription(client_id)
    program_text = await format_program(subscription.exercises, 0)
    await state.update_data(
        exercises=subscription.exercises, client_id=client_id, day=day, subscription=True, day_index=day_index
    )
    await state.set_state(States.program_edit)
    await callback_query.message.answer(
        text=translate(MessageText.program_page, profile.language).format(program=program_text, day=day),
        disable_web_page_preview=True,
        reply_markup=program_edit_kb(profile.language),
    )
    await callback_query.message.delete()
