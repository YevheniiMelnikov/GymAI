from common.functions.chat import *
from common.functions.chat import send_message
from common.functions.exercises import *
from common.functions.menus import *
from common.functions.profiles import get_or_load_profile
from common.functions.text_utils import format_program, get_translated_week_day
from common.functions.utils import program_menu_pagination, short_url
from common.functions.workout_plans import next_day_workout_plan, reset_workout_plan, save_workout_plan
from common.models import Exercise, Program
from texts.resources import ButtonText, MessageText
from texts.text_manager import translate

program_router = Router()


@program_router.callback_query(States.select_service)
async def program_type(callback_query: CallbackQuery, state: FSMContext):
    profile = await get_or_load_profile(callback_query.from_user.id)
    if callback_query.data == "subscription":
        await show_my_subscription_menu(callback_query, profile, state)

    elif callback_query.data == "program":
        await show_my_program_menu(callback_query, profile, state)

    else:
        await show_main_menu(callback_query.message, profile, state)


@program_router.message(States.workouts_number, F.text)
async def workouts_number_choice(message: Message, state: FSMContext):
    await delete_messages(state)
    profile = await get_or_load_profile(message.from_user.id)
    try:
        workouts_per_week = int(message.text)
        if workouts_per_week < 1 or workouts_per_week > 7:
            raise ValueError
    except ValueError:
        await message.answer(translate(MessageText.invalid_content, lang=profile.language))
        await message.delete()
        return

    await state.update_data(split=workouts_per_week, day_index=0, exercises={})
    await message.answer(text=translate(MessageText.program_guide, lang=profile.language))
    day_1_msg = await message.answer(
        translate(MessageText.enter_daily_program, profile.language).format(day=1),
        reply_markup=program_manage_menu(profile.language),
    )
    with suppress(TelegramBadRequest):
        await message.delete()
    await state.update_data(chat_id=message.chat.id, message_ids=[day_1_msg.message_id], day_index=0)
    await state.set_state(States.program_manage)


@program_router.callback_query(States.program_manage)
async def program_manage(callback_query: CallbackQuery, state: FSMContext) -> None:
    await delete_messages(state)
    if callback_query.data == "quit":
        await callback_query.answer()
        profile = await get_or_load_profile(callback_query.from_user.id)
        await show_main_menu(callback_query.message, profile, state)

    elif callback_query.data == "add_next_day":
        await next_day_workout_plan(callback_query, state)

    elif callback_query.data == "reset":
        await reset_workout_plan(callback_query, state)

    elif callback_query.data == "save":
        await save_workout_plan(callback_query, state)


@program_router.message(States.program_manage)
@program_router.message(States.add_exercise_name)
async def set_exercise_name(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    profile = await get_or_load_profile(message.from_user.id)
    link_to_gif = await find_exercise_gif(message.text)
    shorted_link = await short_url(link_to_gif) if link_to_gif else None

    if link_to_gif:
        gif_file_name = link_to_gif.split("/")[-1]
        cache_manager.cache_gif_filename(message.text, gif_file_name)

    await message.answer(translate(MessageText.enter_sets, profile.language), reply_markup=sets_number())
    await message.delete()
    await state.update_data(exercise_name=message.text, gif_link=shorted_link)
    await state.set_state(States.enter_sets)


@program_router.callback_query(States.enter_sets)
async def set_exercise_sets(callback_query: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(sets=callback_query.data)
    profile = await get_or_load_profile(callback_query.from_user.id)
    await callback_query.answer(translate(MessageText.saved, profile.language))
    data = await state.get_data()
    if data.get("edit_mode"):
        await update_exercise_data(callback_query.message, state, profile.language, {"sets": callback_query.data})
        return

    await callback_query.message.answer(translate(MessageText.enter_reps, profile.language), reply_markup=reps_number())
    await callback_query.message.delete()
    await state.set_state(States.enter_reps)


@program_router.callback_query(States.enter_reps)
async def set_exercise_reps(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile = await get_or_load_profile(callback_query.from_user.id)
    await callback_query.answer(translate(MessageText.saved, profile.language))
    data = await state.get_data()
    if data.get("edit_mode"):
        await update_exercise_data(callback_query.message, state, profile.language, {"reps": callback_query.data})
        return

    kb = InlineKeyboardBuilder()
    kb.button(text=translate(ButtonText.quit, profile.language), callback_data="skip_weight")
    weight_message = await callback_query.message.answer(
        translate(MessageText.exercise_weight, profile.language), reply_markup=kb.as_markup(one_time_keyboard=True)
    )
    await state.update_data(
        chat_id=callback_query.message.chat.id, message_ids=[weight_message.message_id], reps=callback_query.data
    )
    await callback_query.message.delete()
    await state.set_state(States.exercise_weight)


@program_router.message(States.exercise_weight)
@program_router.callback_query(States.exercise_weight, F.data == "skip_weight")
async def set_exercise_weight(input_data: CallbackQuery | Message, state: FSMContext) -> None:
    profile = await get_or_load_profile(input_data.from_user.id)
    data = await state.get_data()
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
            await input_data.answer(translate(MessageText.invalid_content, lang=profile.language))
            await input_data.delete()
            return

    with suppress(TelegramBadRequest):
        await message.delete()
    if data.get("edit_mode"):
        await update_exercise_data(message, state, profile.language, {"weight": weight})
        return

    exercises = data.get("exercises", {})
    day_index = data.get("day_index", 0)
    if str(day_index) not in exercises:
        exercises[str(day_index)] = [dict(gif_link=gif_link, name=exercise_name, reps=reps, sets=sets, weight=weight)]
    else:
        exercises[str(day_index)].append(
            dict(gif_link=gif_link, name=exercise_name, reps=reps, sets=sets, weight=weight)
        )
    await state.update_data(exercises=exercises)

    exercise = Exercise(name=exercise_name, sets=sets, reps=reps, gif_link=gif_link, weight=weight)
    await save_exercise(state, exercise, input_data)


@program_router.callback_query(States.workout_survey)
async def workout_results(callback_query: CallbackQuery, state: FSMContext):
    profile = await get_or_load_profile(callback_query.from_user.id)
    data = await state.get_data()
    day = data.get("day")
    exercises = data.get("exercises", {})
    day_index = data.get("day_index", 0)

    program = await format_program({str(day_index): exercises}, day_index)
    if callback_query.data == "answer_yes":
        await callback_query.answer()
        await callback_query.answer(translate(MessageText.keep_going, profile.language), show_alert=True)
        client = cache_manager.get_client_by_id(profile.id)
        coach = cache_manager.get_coach_by_id(client.assigned_to.pop())
        coach_profile = await backend_service.get_profile(coach.id)
        coach_lang = cache_manager.get_profile_info_by_key(coach_profile.get("current_tg_id"), coach.id, "language")
        await send_message(
            recipient=coach,
            text=translate(MessageText.workout_completed, coach_lang).format(name=client.name, program=program),
            state=state,
            reply_markup=workout_feedback(coach_lang, client.id, day),
            include_incoming_message=False,
        )
        await show_main_menu(callback_query.message, profile, state)
    else:
        await callback_query.answer(translate(MessageText.workout_description, profile.language), show_alert=True)
        await state.set_state(States.workout_description)


@program_router.message(States.workout_description)
async def workout_description(message: Message, state: FSMContext):
    profile = await get_or_load_profile(message.from_user.id)
    client = cache_manager.get_client_by_id(profile.id)
    coach = cache_manager.get_coach_by_id(client.assigned_to.pop())
    coach_data = await backend_service.get_profile(coach.id)
    coach_lang = cache_manager.get_profile_info_by_key(coach_data.get("current_tg_id"), coach.id, "language")
    data = await state.get_data()
    day = data.get("day")
    exercises = data.get("exercises")
    day_index = data.get("day_index")
    program = await format_program(exercises, day_index)
    await send_message(
        recipient=coach,
        text=translate(MessageText.workout_feedback, coach_lang).format(
            name=client.name, feedback=message.text, program=program
        ),
        state=state,
        reply_markup=workout_feedback(coach_lang, client.id, day),
        include_incoming_message=False,
    )
    await message.answer(translate(MessageText.keep_going, profile.language))
    await show_main_menu(message, profile, state)


@program_router.callback_query(States.program_edit)
async def manage_exercises(callback_query: CallbackQuery, state: FSMContext):
    profile = await get_or_load_profile(callback_query.from_user.id)
    data = await state.get_data()
    exercises = data.get("exercises", {})
    client_id = data.get("client_id")
    day_index = str(data.get("day_index", 0))

    if callback_query.data == "exercise_add":
        await callback_query.answer()
        exercise_msg = await callback_query.message.answer(translate(MessageText.enter_exercise, profile.language))
        await state.update_data(
            exercise_index=len(exercises) + 1,
            exercises=exercises,
            message_ids=[exercise_msg.message_id],
            chat_id=callback_query.message.chat.id,
        )
        await state.set_state(States.add_exercise_name)

    elif callback_query.data == "quit":
        await callback_query.answer()
        await my_clients_menu(callback_query, profile, state)
        return

    elif callback_query.data == "reset":
        await callback_query.answer()
        if data.get("subscription"):
            subscription_data = cache_manager.get_subscription(client_id).to_dict()
            subscription_data.update(user=client_id, exercises={})
            await backend_service.update_subscription(subscription_data.get("id"), subscription_data)
            cache_manager.update_subscription_data(client_id, {"exercises": None, "user": client_id})
        else:
            if await backend_service.delete_program(client_id):
                cache_manager.delete_program(client_id)
                cache_manager.set_payment_status(client_id, True, "program")
        await state.clear()
        await state.update_data(client_id=client_id, exercises=[], day_index=0)

    elif callback_query.data == "exercise_delete":
        await callback_query.answer()
        await callback_query.message.answer(
            translate(MessageText.select_exercise, profile.language), reply_markup=select_exercise(exercises[day_index])
        )
        await state.set_state(States.delete_exercise)

    elif callback_query.data == "exercise_edit":
        await state.update_data(edit_mode=True)
        await callback_query.message.answer(
            translate(MessageText.select_exercise, profile.language), reply_markup=select_exercise(exercises[day_index])
        )
        await state.set_state(States.edit_exercise)

    elif callback_query.data == "finish_editing":
        await callback_query.answer(translate(ButtonText.done, profile.language))
        client = cache_manager.get_client_by_id(client_id)
        client_data = await backend_service.get_profile(client_id)
        client_lang = cache_manager.get_profile_info_by_key(client_data.get("current_tg_id"), client.id, "language")
        if data.get("subscription"):
            subscription_data = cache_manager.get_subscription(client_id).to_dict()
            subscription_data.update(user=client_id, exercises=exercises)
            await backend_service.update_subscription(subscription_data.get("id"), subscription_data)
            cache_manager.update_subscription_data(client_id, {"exercises": exercises, "user": client_id})
            await send_message(
                recipient=client,
                text=translate(MessageText.new_program, lang=client_lang),
                state=state,
                reply_markup=subscription_view_kb(client_lang),
                include_incoming_message=False,
            )
        else:
            current_program = cache_manager.get_program(client_id)
            split_number = current_program.split_number
            workout_type = current_program.workout_type
            program_text = await format_program(exercises, 0)
            if program_data := await backend_service.save_program(client_id, exercises, split_number):
                program_data.update(workout_type=workout_type)
                cache_manager.set_program(client_id, program_data)
                cache_manager.set_payment_status(client_id, False, "program")
            await send_message(
                recipient=client,
                text=translate(MessageText.new_program, lang=client_lang),
                state=state,
                include_incoming_message=False,
            )
            await send_message(
                recipient=client,
                text=translate(MessageText.program_page, lang=client_lang).format(program=program_text, day=1),
                state=state,
                reply_markup=program_view_kb(client_lang),
                include_incoming_message=False,
            )

        cache_manager.set_client_data(client_id, {"status": "default"})
        await show_main_menu(callback_query.message, profile, state)
        return

    else:
        if data.get("subscription"):
            subscription = cache_manager.get_subscription(client_id)
            split_number = len(subscription.workout_days)
        else:
            program = cache_manager.get_program(client_id)
            split_number = program.split_number

        await state.update_data(split=split_number)
        await program_menu_pagination(state, callback_query)
        return

    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


@program_router.callback_query(States.edit_exercise)
async def select_exercise_to_edit(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    profile = await get_or_load_profile(callback_query.from_user.id)
    data = await state.get_data()
    exercises = data.get("exercises")
    exercise_index = int(callback_query.data)
    current_index = 0
    selected_exercise = None

    for sublist in exercises:
        if isinstance(sublist, dict):
            keys = list(sublist.keys())
            if current_index + len(keys) > exercise_index:
                selected_exercise = sublist.get(keys[exercise_index - current_index])
                break
            current_index += len(keys)
        elif isinstance(sublist, list):
            if current_index + len(sublist) > exercise_index:
                selected_exercise = sublist[exercise_index - current_index]
                break
            current_index += len(sublist)

    await state.update_data(selected_exercise=selected_exercise, exercise_index=exercise_index)
    await callback_query.message.answer(
        translate(MessageText.parameter_to_edit, profile.language), reply_markup=edit_exercise_data(profile.language)
    )
    await state.set_state(States.edit_exercise_parameter)
    await callback_query.message.delete()


@program_router.callback_query(States.edit_exercise_parameter)
async def exercise_edit_options(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    profile = await get_or_load_profile(callback_query.from_user.id)
    if callback_query.data == "weight":
        kb = InlineKeyboardBuilder()
        kb.button(text=translate(ButtonText.quit, profile.language), callback_data="skip_weight")
        await callback_query.message.answer(
            translate(MessageText.exercise_weight, profile.language), reply_markup=kb.as_markup(one_time_keyboard=True)
        )
        await state.set_state(States.exercise_weight)

    elif callback_query.data == "reps":
        await callback_query.message.answer(
            translate(MessageText.enter_reps, profile.language), reply_markup=reps_number()
        )
        await state.set_state(States.enter_reps)

    elif callback_query.data == "sets":
        await callback_query.message.answer(
            translate(MessageText.enter_sets, profile.language), reply_markup=sets_number()
        )
        await state.set_state(States.enter_sets)

    await callback_query.message.delete()


@program_router.callback_query(States.delete_exercise)
async def delete_exercise(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    profile = await get_or_load_profile(callback_query.from_user.id)
    data = await state.get_data()
    exercises = data.get("exercises")
    day_index = str(data.get("day_index"))
    exercise_index = callback_query.data
    daily_exercises = exercises.get(day_index)
    daily_exercises.pop(int(exercise_index))
    await state.update_data(exercises=exercises)
    await state.set_state(States.program_edit)
    await callback_query.message.answer(
        translate(MessageText.continue_editing, profile.language), reply_markup=program_edit_kb(profile.language)
    )
    await callback_query.message.delete()


@program_router.callback_query(States.subscription_manage)
async def subscription_manage(callback_query: CallbackQuery, state: FSMContext):
    profile = await get_or_load_profile(callback_query.from_user.id)
    data = await state.get_data()
    days = data.get("days", [])
    day_index = data.get("day_index", 0)
    exercises = data.get("exercises", {})

    if callback_query.data == "back":
        await my_clients_menu(callback_query, profile, state)
        return

    if callback_query.data == "edit":
        await callback_query.answer()
        program_text = await format_program({str(day_index): exercises[str(day_index)]}, day_index)
        await state.set_state(States.program_edit)
        week_day = get_translated_week_day(profile.language, days[day_index]).lower()
        await callback_query.message.answer(
            text=translate(MessageText.program_page, profile.language).format(program=program_text, day=week_day),
            disable_web_page_preview=True,
            reply_markup=program_edit_kb(profile.language),
        )
        await callback_query.message.delete()
        return

    await state.update_data(split=len(days))
    await program_menu_pagination(state, callback_query)


@program_router.callback_query(States.program_view)
async def program_view(callback_query: CallbackQuery, state: FSMContext):
    profile = await get_or_load_profile(callback_query.from_user.id)
    data = await state.get_data()
    if callback_query.data == "quit":
        await callback_query.answer()
        await state.set_state(States.select_service)
        await callback_query.message.answer(
            text=translate(MessageText.select_service, lang=profile.language),
            reply_markup=select_service(profile.language),
        )
        with suppress(TelegramBadRequest):
            await callback_query.message.delete()
        return

    exercises = data.get("exercises")
    split = data.get("split")
    await state.update_data(exercises=exercises, split=split)
    await program_menu_pagination(state, callback_query)


@program_router.callback_query(States.confirm_subscription_reset)
async def confirm_subscription_reset(callback_query: CallbackQuery, state: FSMContext):
    profile = await get_or_load_profile(callback_query.from_user.id)
    data = await state.get_data()
    if callback_query.data == "yes":
        await callback_query.answer(translate(MessageText.workout_plan_deleted, profile.language), show_alert=True)
        cache_manager.update_subscription_data(profile.id, dict(exercises={}, workout_days=data.get("workout_days")))
        subscription = cache_manager.get_subscription(profile.id)
        await backend_service.update_subscription(subscription.id, subscription.to_dict())
        client = cache_manager.get_client_by_id(profile.id)
        coach = cache_manager.get_coach_by_id(client.assigned_to.pop())
        await send_message(
            recipient=coach,
            text=translate(MessageText.workout_days_changed, profile.language).format(name=client.name),
            state=state,
            reply_markup=incoming_request(profile.language, "subscription", client.id),
            include_incoming_message=False,
        )
    await show_main_menu(callback_query.message, profile, state)
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


@program_router.callback_query(States.program_action_choice)
async def program_action_choice(callback_query: CallbackQuery, state: FSMContext):
    profile = await get_or_load_profile(callback_query.from_user.id)
    data = await state.get_data()
    if callback_query.data == "view":
        await callback_query.answer()
        program = Program.from_dict(data.get("program"))
        program_text = await format_program(program.exercises_by_day, 0)
        await callback_query.message.answer(
            text=translate(MessageText.program_page, lang=profile.language).format(program=program_text, day=1),
            reply_markup=program_view_kb(profile.language),
            disable_web_page_preview=True,
        )
        await state.update_data(exercises=program.exercises_by_day, split=program.split_number, client=True)
        await state.set_state(States.program_view)
    else:
        await callback_query.answer(translate(MessageText.program_delete_warning, profile.language), show_alert=True)
        await show_program_promo_page(callback_query, profile, state)
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()
