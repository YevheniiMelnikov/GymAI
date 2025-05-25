from contextlib import suppress

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards import (
    workout_feedback_kb,
    select_exercise_kb,
    subscription_view_kb,
    program_view_kb,
    edit_exercise_data_kb,
    reps_number_kb,
    sets_number_kb,
    program_manage_kb,
)
from bot.states import States
from core.cache import Cache
from core.services import APIService
from bot.functions.chat import send_message
from bot.functions.exercises import update_exercise_data, save_exercise, find_exercise_gif
from bot.functions.menus import (
    show_main_menu,
    my_clients_menu,
    show_my_subscription_menu,
    show_my_program_menu,
)
from bot.functions.text_utils import format_program
from bot.functions.utils import program_menu_pagination, short_url, delete_messages
from bot.functions.workout_plans import reset_workout_plan, save_workout_plan, next_day_workout_plan
from core.models import Exercise, DayExercises, Profile
from bot.texts.text_manager import msg_text, btn_text

workout_router = Router()


@workout_router.callback_query(States.select_service)
async def program_type(callback_query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    if callback_query.data == "subscription":
        await show_my_subscription_menu(callback_query, profile, state)
    elif callback_query.data == "program":
        await show_my_program_menu(callback_query, profile, state)
    else:
        await show_main_menu(callback_query.message, profile, state)


@workout_router.message(States.workouts_number, F.text)
async def workouts_number_choice(message: Message, state: FSMContext):
    await delete_messages(state)
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    try:
        workouts_per_week = int(message.text)
        if workouts_per_week < 1 or workouts_per_week > 7:
            raise ValueError
    except ValueError:
        await message.answer(msg_text("invalid_content", profile.language))
        await message.delete()
        return

    await state.update_data(split=workouts_per_week, day_index=0, exercises={})
    await message.answer(msg_text("program_guide", profile.language))
    day_1_msg = await message.answer(
        msg_text("enter_daily_program", profile.language).format(day=1),
        reply_markup=program_manage_kb(profile.language, workouts_per_week),
    )
    with suppress(TelegramBadRequest):
        await message.delete()
    await state.update_data(chat_id=message.chat.id, message_ids=[day_1_msg.message_id], day_index=0)
    await state.set_state(States.program_manage)


@workout_router.callback_query(States.program_manage)
async def program_manage(callback_query: CallbackQuery, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    if callback_query.data == "quit":
        await callback_query.answer()
        await show_main_menu(callback_query.message, profile, state)
    elif callback_query.data == "add_next_day":
        await next_day_workout_plan(callback_query, state)
    elif callback_query.data == "reset":
        await reset_workout_plan(callback_query, state)
    elif callback_query.data == "save":
        await save_workout_plan(callback_query, state)


@workout_router.message(States.program_manage)
@workout_router.message(States.add_exercise_name)
async def set_exercise_name(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    link_to_gif = await find_exercise_gif(message.text)
    shorted_link = await short_url(link_to_gif) if link_to_gif else None

    if link_to_gif:
        gif_file_name = link_to_gif.split("/")[-1]
        await Cache.workout.cache_gif_filename(message.text, gif_file_name)

    await message.answer(msg_text("enter_sets", profile.language), reply_markup=sets_number_kb())
    await message.delete()
    await state.update_data(exercise_name=message.text, gif_link=shorted_link)
    await state.set_state(States.enter_sets)


@workout_router.callback_query(States.enter_sets)
async def set_exercise_sets(callback_query: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(sets=callback_query.data)
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    await callback_query.answer(msg_text("saved", profile.language))
    if data.get("edit_mode"):
        await update_exercise_data(callback_query.message, state, profile.language, {"sets": callback_query.data})
        return

    await callback_query.message.answer(msg_text("enter_reps", profile.language), reply_markup=reps_number_kb())
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()
    await state.set_state(States.enter_reps)


@workout_router.callback_query(States.enter_reps)
async def set_exercise_reps(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    await callback_query.answer(msg_text("saved", profile.language))
    if data.get("edit_mode"):
        await update_exercise_data(callback_query.message, state, profile.language, {"reps": callback_query.data})
        return

    kb = InlineKeyboardBuilder()
    kb.button(text=btn_text("quit", profile.language), callback_data="skip_weight")
    weight_message = await callback_query.message.answer(
        msg_text("exercise_weight", profile.language), reply_markup=kb.as_markup(one_time_keyboard=True)
    )
    await state.update_data(
        chat_id=callback_query.message.chat.id, message_ids=[weight_message.message_id], reps=callback_query.data
    )
    await callback_query.message.delete()
    await state.set_state(States.exercise_weight)


@workout_router.message(States.exercise_weight)
@workout_router.callback_query(States.exercise_weight, F.data == "skip_weight")
async def set_exercise_weight(input_data: CallbackQuery | Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    exercise_name = data.get("exercise_name")
    sets = data.get("sets")
    reps = data.get("reps")
    gif_link = data.get("gif_link")
    await delete_messages(state)

    if isinstance(input_data, CallbackQuery):
        weight = None
        await input_data.answer()
        message = input_data.message
    else:
        try:
            weight = int(input_data.text)
            message = input_data
        except ValueError:
            await input_data.answer(msg_text("invalid_content", profile.language))
            await input_data.delete()
            return

    with suppress(TelegramBadRequest):
        await message.delete()
    if data.get("edit_mode"):
        await update_exercise_data(message, state, profile.language, {"weight": weight})
        return

    if data.get("subscription"):
        subscription = await Cache.workout.get_subscription(data.get("client_id"))
        exercises: list[DayExercises] = subscription.exercises
    else:
        exercises = [DayExercises.model_validate(e) for e in data.get("exercises", [])]

    day_index = str(data.get("day_index", 0))
    day_entry = next((d for d in exercises if d.day == day_index), None)
    new_exercise = Exercise(
        name=exercise_name, sets=sets, reps=reps, gif_link=gif_link, weight=str(weight) if weight is not None else None
    )

    if day_entry:
        day_entry.exercises.append(new_exercise)
    else:
        exercises.append(DayExercises(day=day_index, exercises=[new_exercise]))

    await state.update_data(exercises=exercises)
    await save_exercise(state, new_exercise, input_data)


@workout_router.callback_query(States.workout_survey)
async def send_workout_results(callback_query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    day = data.get("day")
    day_index = data.get("day_index", 0)
    exercises = [DayExercises.model_validate(e) for e in data.get("exercises", [])]
    program = await format_program(exercises, day_index)

    if callback_query.data == "completed":
        await callback_query.answer()
        await callback_query.answer(msg_text("keep_going", profile.language), show_alert=True)

        client = await Cache.client.get_client(profile.id)
        coach = await Cache.coach.get_coach(client.assigned_to.pop())
        coach_profile = await APIService.profile.get_profile(coach.id)
        coach_lang = coach_profile.language

        await send_message(
            recipient=coach,
            text=msg_text("workout_completed", coach_lang).format(name=client.name, program=program),
            state=state,
            reply_markup=workout_feedback_kb(coach_lang, client.id, day),
            include_incoming_message=False,
        )

        await show_main_menu(callback_query.message, profile, state)

    else:
        await callback_query.answer(msg_text("workout_description", profile.language), show_alert=True)
        await state.set_state(States.workout_description)

    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


@workout_router.message(States.workout_description)
async def workout_description(message: Message, state: FSMContext):
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    client = await Cache.client.get_client(profile.id)
    coach = await Cache.coach.get_coach(client.assigned_to.pop())
    coach_profile = await APIService.profile.get_profile(coach.id)
    coach_lang = coach_profile.language

    day_index = data.get("day_index")
    exercises = [DayExercises.model_validate(e) for e in data.get("exercises", [])]
    day_data = next((d for d in exercises if d.day == str(day_index)), None)
    program = await format_program(exercises, day_index) if day_data else ""

    await send_message(
        recipient=coach,
        text=msg_text("workout_feedback", coach_lang).format(
            name=client.name,
            feedback=message.text,
            program=program,
        ),
        state=state,
        reply_markup=workout_feedback_kb(coach_lang, client.id, data.get("day")),
        include_incoming_message=False,
    )

    await message.answer(msg_text("keep_going", profile.language))
    await show_main_menu(message, profile, state)


@workout_router.callback_query(States.program_edit)
async def manage_exercises(callback_query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    exercises = [DayExercises.model_validate(e) for e in data.get("exercises", [])]
    client_id = data.get("client_id")
    day_index = str(data.get("day_index", 0))

    day_data = next((d for d in exercises if d.day == day_index), None)

    if callback_query.data == "exercise_add":
        await callback_query.answer()
        exercise_msg = await callback_query.message.answer(msg_text("enter_exercise", profile.language))
        if not day_data:
            exercises.append(DayExercises(day=day_index, exercises=[]))
        else:
            await state.update_data(exercise_index=len(day_data.exercises))
        await state.update_data(
            exercises=exercises,
            message_ids=[exercise_msg.message_id],
            chat_id=callback_query.message.chat.id,
            edit_mode=False,
        )
        await state.set_state(States.add_exercise_name)

    elif callback_query.data == "quit":
        await callback_query.answer()
        await my_clients_menu(callback_query, profile, state)
        return

    elif callback_query.data == "reset":
        await reset_workout_plan(callback_query, state)

    elif callback_query.data == "exercise_delete":
        await callback_query.answer()
        if day_data:
            await callback_query.message.answer(
                msg_text("select_exercise", profile.language),
                reply_markup=select_exercise_kb(day_data.exercises),
            )
        else:
            await callback_query.message.answer(msg_text("no_exercises_found", profile.language))
        await state.set_state(States.delete_exercise)

    elif callback_query.data == "exercise_edit":
        await state.update_data(edit_mode=True)
        if day_data:
            await callback_query.message.answer(
                msg_text("select_exercise", profile.language),
                reply_markup=select_exercise_kb(day_data.exercises),
            )
        else:
            await callback_query.message.answer(msg_text("no_exercises_found", profile.language))
        await state.set_state(States.edit_exercise)

    elif callback_query.data == "finish_editing":
        await callback_query.answer(btn_text("done", profile.language))
        client_profile = await APIService.profile.get_profile(client_id)
        client_lang = client_profile.language
        client = await Cache.client.get_client(client_id)

        if data.get("subscription"):
            subscription = await Cache.workout.get_subscription(client_id)
            subscription_data = subscription.model_dump()
            subscription_data.update(client_profile=client_id, exercises=exercises)
            await APIService.workout.update_subscription(subscription_data.get("id"), subscription_data)
            await Cache.workout.update_subscription(
                profile_id=client_id,
                updates=dict(exercises=exercises, client_profile=client_id),
            )
            await Cache.workout.reset_payment_status(client_id, "subscription")
            await send_message(
                recipient=client,
                text=msg_text("new_program", client_lang),
                state=state,
                reply_markup=subscription_view_kb(client_lang),
                include_incoming_message=False,
            )
        else:
            current_program = await Cache.workout.get_program(client_id)
            program_text = await format_program(exercises, 0)
            if program := await APIService.workout.save_program(
                client_id, exercises, current_program.split_number, current_program.wishes
            ):
                program_data = program.model_dump()
                program_data.update(workout_type=current_program.workout_type)
                await Cache.workout.save_program(client_id, program_data)
                await Cache.workout.reset_payment_status(client_id, "program")
            await send_message(
                recipient=client,
                text=msg_text("new_program", client_lang),
                state=state,
                include_incoming_message=False,
            )
            await send_message(
                recipient=client,
                text=msg_text("program_page", client_lang).format(program=program_text, day=1),
                state=state,
                reply_markup=program_view_kb(client_lang),
                include_incoming_message=False,
            )

        await Cache.client.update_client(client_id, dict(status="default"))
        await show_main_menu(callback_query.message, profile, state)
        return

    else:
        if data.get("subscription"):
            subscription = await Cache.workout.get_subscription(client_id)
            split_number = len(subscription.workout_days)
        else:
            program = await Cache.workout.get_program(client_id)
            split_number = program.split_number

        await state.update_data(split=split_number)
        await program_menu_pagination(state, callback_query)
        return

    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


@workout_router.callback_query(States.edit_exercise)
async def select_exercise_to_edit(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    exercises = [DayExercises.model_validate(e) for e in data.get("exercises", [])]
    exercise_index = int(callback_query.data)

    flat_exercises = [
        (day_idx, idx, ex) for day_idx, day in enumerate(exercises) for idx, ex in enumerate(day.exercises)
    ]

    if exercise_index >= len(flat_exercises):
        await callback_query.message.answer(msg_text("invalid_content", profile.language))
        return

    day_idx, local_idx, selected_exercise = flat_exercises[exercise_index]

    await state.update_data(
        selected_exercise=selected_exercise,
        exercise_index=exercise_index,
        selected_day_index=day_idx,
        selected_ex_index=local_idx,
    )
    await callback_query.message.answer(
        msg_text("parameter_to_edit", profile.language), reply_markup=edit_exercise_data_kb(profile.language)
    )
    await callback_query.message.delete()
