from __future__ import annotations

from typing import cast, Any
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from bot.utils.text import get_translated_week_day
from bot.utils.other import delete_messages, answer_msg, del_msg
from bot.keyboards import program_edit_kb, program_manage_kb
from bot.states import States
from bot.texts.text_manager import msg_text
from config.env_settings import settings
from core.schemas import Exercise, DayExercises, Subscription, Profile
from core.exceptions import ProgramNotFoundError, SubscriptionNotFoundError, ProfileNotFoundError


async def save_exercise(
    state: FSMContext, exercise: Exercise, input_data: Message | CallbackQuery, profile: Profile
) -> None:
    data = await state.get_data()
    await delete_messages(state)

    if not input_data.from_user:
        return

    client_id_str = data.get("client_id")
    if client_id_str is None:
        logger.error("client_id not found in state for save_exercise")
        return

    client_id = int(client_id_str)
    day_index = int(data.get("day_index", 0))

    raw_exercises = data.get("exercises", [])
    exercises: list[DayExercises] = [
        DayExercises.model_validate(ex) if isinstance(ex, dict) else ex for ex in raw_exercises
    ]

    day_key = str(day_index)
    day_entry = next((d for d in exercises if d.day == day_key), None)

    if day_entry is None:
        day_entry = DayExercises(day=day_key, exercises=[exercise])
        exercises.append(day_entry)
    elif not any(ex.name == exercise.name for ex in day_entry.exercises):
        day_entry.exercises.append(exercise)

    if data.get("subscription"):
        days: list[str] = data.get("days", [])
        try:
            current_day_code = days[day_index]
        except IndexError:
            logger.warning(f"Invalid day_index {day_index} for days: {days}")
            current_day_code = "monday"
        day_label = get_translated_week_day(profile.language, current_day_code).lower()
        split_number = len(days)
    else:
        day_label = day_index + 1
        split_number = data.get("split")
        if split_number is None:
            try:
                from core.cache import Cache

                program = await Cache.workout.get_program(client_id)
                split_number = program.split_number
            except ProgramNotFoundError:
                logger.warning(
                    f"Program not found for client {client_id} in save_exercise, defaulting split_number to 1."
                )
                split_number = 1

    program_text = await format_program(exercises, day_index)

    msg: Message | None = None
    if isinstance(input_data, CallbackQuery) and isinstance(input_data.message, Message):
        msg = input_data.message
    elif isinstance(input_data, Message):
        msg = input_data

    if msg is None:
        return

    exercise_msg = await answer_msg(msg, msg_text("enter_exercise", profile.language))
    program_msg = await answer_msg(
        msg,
        msg_text("program_page", profile.language).format(program=program_text, day=day_label),
        reply_markup=program_manage_kb(profile.language, split_number),
        disable_web_page_preview=True,
    )

    message_ids = [m.message_id for m in [exercise_msg, program_msg] if m]

    await state.update_data(
        chat_id=msg.chat.id,
        message_ids=message_ids,
        exercises=exercises,
        day_index=day_index,
        split=split_number,
    )
    await state.set_state(States.program_manage)


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
    try:
        from core.cache import Cache

        profile = await Cache.profile.get_profile(callback_query.from_user.id)
    except ProfileNotFoundError:
        logger.warning(f"Profile not found for user {callback_query.from_user.id} in edit_subscription_exercises")
        await callback_query.answer(msg_text("error_generic", settings.DEFAULT_LANG), show_alert=True)
        return

    parts = cast(str, callback_query.data).split("_")
    client_id = int(parts[1])
    day = parts[2]

    subscription: Subscription
    try:
        from core.cache import Cache

        subscription = await Cache.workout.get_latest_subscription(client_id)
    except SubscriptionNotFoundError:
        logger.error(f"Subscription not found for client {client_id} in edit_subscription_exercises.")
        await callback_query.answer(msg_text("subscription_not_found_error", profile.language), show_alert=True)
        return

    language = cast(str, profile.language or settings.DEFAULT_LANG)
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
        if exercise.set_id is not None:
            line += f" | Set {exercise.set_id}"
        if exercise.weight:
            line += f" | {exercise.weight} kg"
        if exercise.gif_link:
            line += f" | <a href='{exercise.gif_link}'>GIF</a>"
        program_lines.append(line)

    return "\n".join(program_lines)


async def format_full_program(exercises: list[DayExercises]) -> str:
    lines: list[str] = []
    for day_entry in sorted(exercises, key=lambda d: int(d.day)):
        lines.append(f"<b>Day {day_entry.day}</b>")
        for idx, exercise in enumerate(day_entry.exercises):
            line = f"{idx + 1}. {exercise.name} | {exercise.sets} x {exercise.reps}"
            if exercise.set_id is not None:
                line += f" | Set {exercise.set_id}"
            if exercise.weight:
                line += f" | {exercise.weight} kg"
            lines.append(line)
        lines.append("")
    return "\n".join(lines).strip()


async def create_exercise(
    data: dict,
    exercises_to_modify: list[DayExercises],
    state: FSMContext,
    weight: int | None,
) -> Exercise:
    day_index = str(data.get("day_index", 0))
    day_entry = next((d for d in exercises_to_modify if d.day == day_index), None)

    new_exercise = Exercise(
        name=data.get("exercise_name", ""),
        sets=data.get("sets", ""),
        reps=data.get("reps", ""),
        gif_link=data.get("gif_link"),
        weight=str(weight) if weight is not None else None,
        set_id=data.get("set_id"),
    )

    if day_entry:
        day_entry.exercises.append(new_exercise)
    else:
        exercises_to_modify.append(DayExercises(day=day_index, exercises=[new_exercise]))

    await state.update_data(exercises=[de.model_dump() for de in exercises_to_modify])
    return new_exercise
