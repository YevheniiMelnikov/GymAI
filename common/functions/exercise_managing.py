import os
from contextlib import suppress
from dataclasses import asdict

import loguru
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import program_view_kb, program_edit_kb, program_manage_menu, subscription_manage_menu
from bot.states import States
from common.file_manager import gif_manager
from common.functions.menus import handle_my_clients
from common.models import Profile, Exercise
from common.user_service import user_service
from common.utils import get_translated_week_day, format_program
from texts.exercises import exercise_dict
from texts.text_manager import translate, MessageText

bot = Bot(os.environ.get("BOT_TOKEN"))
logger = loguru.logger


async def handle_program_pagination(state: FSMContext, callback_query: CallbackQuery) -> None:
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)

    if callback_query.data == "quit":
        await handle_my_clients(callback_query, profile, state)
        return

    data = await state.get_data()
    current_day = data.get("day_index", 0)
    exercises = data.get("exercises", {})
    split_number = data.get("split")

    if callback_query.data == "prev_day":
        current_day -= 1
    else:
        current_day += 1

    if current_day < 0 or current_day >= split_number:
        await callback_query.answer(translate(MessageText.out_of_range, profile.language))
        current_day = max(0, min(current_day, split_number - 1))

    await state.update_data(day_index=current_day)
    program_text = await format_program(exercises, current_day)

    if data.get("client"):
        reply_markup = program_view_kb(profile.language)
        state_to_set = States.program_view
    else:
        reply_markup = program_edit_kb(profile.language)
        state_to_set = States.program_edit

    with suppress(TelegramBadRequest):
        await callback_query.message.edit_text(
            text=translate(MessageText.program_page, profile.language).format(
                program=program_text, day=current_day + 1
            ),
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )

    await state.set_state(state_to_set)
    await callback_query.answer()


async def handle_subscription_action(
    callback_query: CallbackQuery, profile: Profile, client_id: str, state: FSMContext
) -> None:
    subscription = user_service.storage.get_subscription(client_id)

    if not subscription or not subscription.enabled:
        await callback_query.answer(translate(MessageText.payment_required, profile.language))
        return

    await callback_query.answer()
    days = subscription.workout_days

    if not subscription.exercises:
        await callback_query.message.answer(translate(MessageText.no_program, profile.language))
        workouts_per_week = len(subscription.workout_days)
        await callback_query.message.answer(
            translate(MessageText.workouts_per_week, lang=profile.language).format(days=workouts_per_week)
        )
        await callback_query.message.answer(text=translate(MessageText.program_guide, lang=profile.language))
        day_1_msg = await callback_query.message.answer(
            translate(MessageText.enter_daily_program, profile.language).format(day=1),
            reply_markup=program_manage_menu(profile.language),
        )
        await state.update_data(
            day_1_msg=day_1_msg.message_id,
            split=workouts_per_week,
            days=days,
            day_index=0,
            exercises={},
            client_id=client_id,
            subscription=True,
        )
        await state.set_state(States.program_manage)

    else:
        program_text = await format_program({days[0]: subscription.exercises["0"]}, days[0])
        week_day = get_translated_week_day(profile.language, days[0])
        del_msg = await callback_query.message.answer(
            text=translate(MessageText.program_page, profile.language).format(program=program_text, day=week_day),
            reply_markup=subscription_manage_menu(profile.language),
            disable_web_page_preview=True,
        )
        await state.update_data(
            del_msg=del_msg.message_id,
            exercises=subscription.exercises,
            days=days,
            client_id=client_id,
            day_index=0,
            subscription=True,
        )
        await state.set_state(States.subscription_manage)

    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


async def manage_program(callback_query: CallbackQuery, profile: Profile, client_id: str, state: FSMContext) -> None:
    program_paid = user_service.storage.check_payment_status(client_id, "program")
    workout_data = user_service.storage.get_program(str(client_id))

    if not program_paid and not workout_data:
        await callback_query.answer(
            text=translate(MessageText.payment_required, lang=profile.language), show_alert=True
        )
        return

    if workout_data and workout_data.exercises_by_day:
        program = await format_program(workout_data.exercises_by_day, 0)
        del_msg = await callback_query.message.answer(
            text=translate(MessageText.program_page, lang=profile.language).format(program=program, day=1),
            reply_markup=program_edit_kb(profile.language),
            disable_web_page_preview=True,
        )
        await state.update_data(
            exercises=workout_data.exercises_by_day, del_msg=del_msg.message_id, client_id=client_id, day_index=0
        )
        await state.set_state(States.program_edit)
        await callback_query.message.delete()
        return

    else:
        del_msg = await callback_query.message.answer(text=translate(MessageText.no_program, lang=profile.language))

    await state.update_data(del_msg=del_msg.message_id, client_id=client_id)
    await callback_query.message.answer(translate(MessageText.workouts_number, profile.language))
    await state.set_state(States.workouts_number)
    await callback_query.message.delete()


async def save_exercise(state: FSMContext, exercise: Exercise, input_data: Message | CallbackQuery) -> None:
    data = await state.get_data()

    for msg_key in ["del_msg", "exercise_msg", "program_msg", "day_1_msg", "weight_msg"]:
        if del_msg := data.get(msg_key):
            with suppress(TelegramBadRequest):
                await input_data.bot.delete_message(
                    input_data.chat.id if isinstance(input_data, Message) else input_data.message.chat.id, del_msg
                )

    profile = user_service.storage.get_current_profile(input_data.from_user.id)
    day_index = data.get("day_index", 0)
    exercises = data.get("exercises", {})

    if data.get("subscription"):
        days = data.get("days")
        current_day = days[day_index]
        day = get_translated_week_day(profile.language, current_day)
        if current_day not in exercises:
            exercises[day_index] = [asdict(exercise)]
        else:
            exercises[day_index].append(asdict(exercise))
        program = await format_program({days[day_index]: exercises[day_index]}, days[day_index])
    else:
        day = day_index + 1
        if day_index not in exercises:
            exercises[day_index] = [asdict(exercise)]
        else:
            exercises[day_index].append(asdict(exercise))
        program = await format_program({str(day_index): exercises[day_index]}, day_index)

    exercise_msg = await (input_data.answer if isinstance(input_data, Message) else input_data.message.answer)(
        translate(MessageText.enter_exercise, profile.language)
    )
    program_msg = await exercise_msg.answer(
        text=translate(MessageText.program_page, profile.language).format(program=program, day=day),
        reply_markup=program_manage_menu(profile.language),
        disable_web_page_preview=True,
    )

    await state.update_data(
        exercise_msg=exercise_msg.message_id,
        program_msg=program_msg.message_id,
        exercises=exercises,
        day_index=day_index + 1,
    )
    await state.set_state(States.program_manage)


async def show_exercises(callback_query: CallbackQuery, state: FSMContext, profile: Profile) -> None:
    data = await state.get_data()
    exercises = data.get("exercises", {})
    updated_exercises = {str(index): exercise for index, exercise in enumerate(exercises.values())}
    program = await format_program(updated_exercises, day=0)

    await callback_query.message.answer(
        text=translate(MessageText.program_page, lang=profile.language).format(program=program, day=1),
        reply_markup=program_view_kb(profile.language),
        disable_web_page_preview=True,
    )

    await state.update_data(client=True)
    await state.set_state(States.program_view)
    await callback_query.message.delete()


async def find_related_gif(exercise: str) -> str | None:
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
