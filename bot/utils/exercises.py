from __future__ import annotations

from typing import cast, Any
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from bot.utils.text import get_translated_week_day
from bot.utils.other import delete_messages, answer_msg, del_msg
from bot.keyboards import program_edit_kb, program_manage_kb
from bot.states import States
from bot.texts.exercises import exercise_dict
from bot.texts.text_manager import msg_text
from config.env_settings import Settings
from core.cache import Cache
from core.models import Exercise, DayExercises
from core.services.outer.gstorage_service import gif_manager


async def save_exercise(state: FSMContext, exercise: Exercise, input_data: Message | CallbackQuery) -> None:
    data = await state.get_data()
    await delete_messages(state)

    if not input_data.from_user:
        return

    profile = await Cache.profile.get_profile(input_data.from_user.id)
    assert profile
    client_id = cast(int | None, data.get("client_id"))
    if not client_id:
        return

    day_index = cast(int, data.get("day_index", 0))
    exercises: list[DayExercises] = data.get("exercises", [])
    day_str = str(day_index)
    day_entry = next((d for d in exercises if d.day == day_str), None)
    lang = cast(str, profile.language or Settings.DEFAULT_LANG)

    if not day_entry:
        day_entry = DayExercises(day=day_str, exercises=[exercise])
        exercises.append(day_entry)
    elif not any(ex.name == exercise.name for ex in day_entry.exercises):
        day_entry.exercises.append(exercise)

    if data.get("subscription"):
        days: list[str] = cast(list[str], data.get("days"))
        current_day = days[day_index]
        day_label = get_translated_week_day(lang, current_day).lower()
        split_number = len(days)
    else:
        day_label = day_index + 1
        split_number = cast(int | None, data.get("split"))
        if split_number is None:
            program = await Cache.workout.get_program(client_id)
            split_number = program.split_number if program else 1

    program = await format_program(exercises, day_index)

    msg: Message | None = None
    if isinstance(input_data, CallbackQuery) and isinstance(input_data.message, Message):
        msg = input_data.message
    elif isinstance(input_data, Message):
        msg = input_data

    if not msg:
        return

    exercise_msg = await answer_msg(msg, msg_text("enter_exercise", lang))
    program_msg = await answer_msg(
        msg,
        msg_text("program_page", lang).format(program=program, day=day_label),
        reply_markup=program_manage_kb(lang, split_number),
        disable_web_page_preview=True,
    )

    message_ids = []
    if exercise_msg:
        message_ids.append(exercise_msg.message_id)
    if program_msg:
        message_ids.append(program_msg.message_id)

    await state.update_data(
        chat_id=msg.chat.id,
        message_ids=message_ids,
        exercises=exercises,
        day_index=day_index,
        split=split_number,
    )
    await state.set_state(States.program_manage)


async def find_exercise_gif(exercise: str) -> str | None:
    try:
        exercise_lc = exercise.lower()
        for filename, synonyms in exercise_dict.items():
            if exercise_lc in (syn.lower() for syn in synonyms):
                cached = await Cache.workout.get_exercise_gif(exercise_lc)
                if cached:
                    return f"https://storage.googleapis.com/{gif_manager.bucket_name}/{cached}"

                blobs = list(gif_manager.bucket.list_blobs(prefix=filename))
                if blobs:
                    blob = blobs[0]
                    if blob.exists():
                        file_url = f"https://storage.googleapis.com/{gif_manager.bucket_name}/{blob.name}"
                        for syn in synonyms:
                            await Cache.workout.cache_gif_filename(syn.lower(), blob.name)
                        return file_url
    except Exception as e:
        logger.error(f"Failed to find gif for exercise {exercise}: {e}")

    logger.debug(f"No matching file found for exercise: {exercise}")
    return None


async def update_exercise_data(message: Message, state: FSMContext, lang: str, updated_option: dict) -> None:
    data = await state.get_data()
    exercises: list[DayExercises] = data.get("exercises", [])
    day_index = str(data.get("selected_day_index", data.get("day_index", 0)))
    exercise_index = data.get("selected_ex_index", 0)

    day_entry = next((d for d in exercises if d.day == day_index), None)
    if not day_entry:
        return

    selected_ex = day_entry.exercises[exercise_index]
    for k, v in updated_option.items():
        setattr(selected_ex, k, v)

    program = await format_program(exercises, int(day_index))
    await state.update_data(exercises=exercises)
    await state.set_state(States.program_edit)

    await answer_msg(
        message,
        msg_text("program_page", lang).format(program=program, day=int(day_index) + 1),
        disable_web_page_preview=True,
    )
    await answer_msg(
        message,
        msg_text("continue_editing", lang),
        reply_markup=program_edit_kb(lang),
    )
    await del_msg(cast(Message | CallbackQuery | None, message))


async def edit_subscription_exercises(callback_query: CallbackQuery, state: FSMContext) -> None:
    if not callback_query.from_user or not callback_query.data:
        return

    profile = await Cache.profile.get_profile(callback_query.from_user.id)
    assert profile
    parts = cast(str, callback_query.data).split("_")
    client_id = int(parts[1])
    day = parts[2]

    subscription = await Cache.workout.get_subscription(client_id)
    if not subscription:
        return

    language = cast(str, profile.language or "ua")
    week_day = get_translated_week_day(language, day).lower()
    day_index = subscription.workout_days.index(day)
    program_text = await format_program(subscription.exercises, day_index)

    await state.update_data(
        exercises=subscription.exercises,
        client_id=client_id,
        day=day,
        subscription=True,
        day_index=day_index,
        days=subscription.workout_days,
        completed_days=len(subscription.workout_days),
    )
    await state.set_state(States.program_edit)
    if callback_query.message and isinstance(callback_query.message, Message):
        await answer_msg(
            callback_query.message,
            msg_text("program_page", language).format(program=program_text, day=week_day),
            disable_web_page_preview=True,
            reply_markup=program_edit_kb(language),
        )
        await del_msg(callback_query.message)


def serialize_day_exercises(exercises: list[DayExercises]) -> dict[str, list[dict[str, Any]]]:
    return {day.day: [e.model_dump() for e in day.exercises] for day in exercises if isinstance(day, DayExercises)}


async def format_program(exercises: list[DayExercises], day: int) -> str:
    day_key = str(day)
    day_entry = next((d for d in exercises if d.day == day_key), None)
    if not day_entry:
        return ""

    program_lines = []
    for idx, exercise in enumerate(day_entry.exercises):
        line = f"{idx + 1}. {exercise.name} | {exercise.sets} x {exercise.reps}"
        if exercise.weight:
            line += f" | {exercise.weight} kg"
        if exercise.gif_link:
            line += f" | <a href='{exercise.gif_link}'>GIF</a>"
        program_lines.append(line)

    return "\n".join(program_lines)
