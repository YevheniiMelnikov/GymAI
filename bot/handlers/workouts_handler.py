from contextlib import suppress
from dataclasses import asdict

import loguru
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards import *
from bot.states import States
from common.functions import *
from common.models import Exercise
from common.user_service import user_service
from common.utils import short_url
from texts.text_manager import ButtonText, MessageText, translate

program_router = Router()
logger = loguru.logger


@program_router.callback_query(States.select_service)
async def program_type(callback_query: CallbackQuery, state: FSMContext):
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    if callback_query.data == "subscription":
        subscription = user_service.storage.get_subscription(profile.id)
        if not subscription or not subscription.enabled:
            subscription_img = (
                f"https://storage.googleapis.com/bot_payment_options/subscription_{profile.language}.jpeg"
            )
            await callback_query.message.answer_photo(
                photo=subscription_img,
                reply_markup=choose_payment_options(profile.language, "subscription"),
            )
            await state.set_state(States.payment_choice)
        else:
            if exercises := subscription.exercises:
                await state.update_data(exercises=exercises)
                await show_subscription_page(callback_query, state, subscription)
            else:
                await callback_query.answer(translate(MessageText.program_not_ready, profile.language), show_alert=True)

        with suppress(TelegramBadRequest):
            await callback_query.message.delete()

    elif callback_query.data == "program":
        if program := user_service.storage.get_program(profile.id):
            program_paid = user_service.storage.check_payment_status(profile.id, "program")
            if program_paid:
                await callback_query.answer(translate(MessageText.program_not_ready, profile.language), show_alert=True)
                return
            else:
                program_text = await format_program(program.exercises_by_day, 1)
                await callback_query.message.answer(
                    text=translate(MessageText.program_page, lang=profile.language).format(program=program_text, day=1),
                    reply_markup=program_view_kb(profile.language),
                    disable_web_page_preview=True,
                )
                with suppress(TelegramBadRequest):
                    await callback_query.message.delete()
                await state.update_data(exercises=program.exercises_by_day, split=program.split_number)
                await state.set_state(States.program_view)
        else:
            program_img = f"https://storage.googleapis.com/bot_payment_options/program_{profile.language}.jpeg"
            await callback_query.message.answer_photo(
                photo=program_img,
                reply_markup=choose_payment_options(profile.language, "program"),
            )
            await state.set_state(States.payment_choice)
        with suppress(TelegramBadRequest):
            await callback_query.message.delete()
    else:
        await state.set_state(States.main_menu)
        await show_main_menu(callback_query.message, profile, state)


@program_router.message(States.workouts_number, F.text)
async def workouts_number_choice(message: Message, state: FSMContext):
    profile = user_service.storage.get_current_profile(message.from_user.id)
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
    await state.update_data(day_1_msg=day_1_msg.message_id, day_index=0)
    await state.set_state(States.program_manage)


@program_router.callback_query(States.program_manage)
async def program_manage(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    data = await state.get_data()
    split_number = data.get("split")
    client_id = data.get("client_id")
    completed_days = data.get("day_index", 0)
    exercises = data.get("exercises", {})

    if callback_query.data == "quit":
        await show_main_menu(callback_query.message, profile, state)
        await state.set_state(States.main_menu)

    elif callback_query.data == "next":
        if exercises:
            if completed_days < split_number:
                await callback_query.answer("⏭")

                if "program_msg" in data:
                    with suppress(TelegramBadRequest):
                        await callback_query.message.bot.delete_message(
                            callback_query.message.chat.id, data["program_msg"]
                        )

                program = await format_program(exercises, completed_days)
                program_msg = await callback_query.message.answer(
                    text=translate(MessageText.program_page, profile.language).format(
                        program=program, day=completed_days + 1
                    ),
                    reply_markup=program_manage_menu(profile.language),
                )
                await state.update_data(program_msg=program_msg.message_id)
                with suppress(TelegramBadRequest):
                    await callback_query.message.delete()
            else:
                await callback_query.answer(translate(MessageText.out_of_range, profile.language))
        else:
            await callback_query.answer(text=translate(MessageText.no_exercises_to_save, lang=profile.language))

    elif callback_query.data == "reset":
        await callback_query.answer(translate(ButtonText.done, profile.language))
        if data.get("subscription"):
            subscription_data = user_service.storage.get_subscription(client_id).to_dict()
            subscription_data.update(user=client_id, exercises=None)
            await user_service.update_subscription(subscription_data.get("id"), subscription_data)
            await user_service.storage.save_subscription(client_id, subscription_data)
        else:
            if await user_service.delete_program(str(client_id)):
                user_service.storage.delete_program(str(client_id))
        await state.clear()
        await callback_query.message.answer(translate(MessageText.enter_daily_program, profile.language).format(day=1))
        await state.update_data(client_id=client_id, exercises=[], day_index=0)
        await state.set_state(States.program_manage)
        with suppress(TelegramBadRequest):
            await callback_query.message.delete()

    elif callback_query.data == "save":
        if exercises:
            if completed_days == split_number:
                await callback_query.answer(text=translate(MessageText.saved, lang=profile.language))
                client = user_service.storage.get_client_by_id(client_id)
                client_lang = user_service.storage.get_profile_info_by_key(client.tg_id, client.id, "language")
                if data.get("subscription"):
                    subscription_data = user_service.storage.get_subscription(client_id).to_dict()
                    subscription_data.update(user=client_id, exercises=exercises)
                    user_service.storage.save_subscription(client_id, subscription_data)
                    await user_service.update_subscription(subscription_data.get("id"), subscription_data)
                    await send_message(
                        recipient=client,
                        text=translate(MessageText.new_program, lang=client_lang),
                        state=state,
                        reply_markup=subscription_view_kb(client_lang),
                        include_incoming_message=False,
                    )
                else:
                    program = await format_program(exercises, 0)
                    await user_service.save_program(str(client_id), exercises, split_number)
                    await send_message(
                        recipient=client,
                        text=translate(MessageText.new_program, lang=client_lang),
                        state=state,
                        include_incoming_message=False,
                    )
                    await send_message(
                        recipient=client,
                        text=translate(MessageText.program_page, lang=client_lang).format(program=program, day=1),
                        state=state,
                        reply_markup=program_view_kb(client_lang),
                        include_incoming_message=False,
                    )
                await state.clear()
                await state.set_state(States.main_menu)
                await show_main_menu(callback_query.message, profile, state)
            else:
                await callback_query.answer(translate(MessageText.complete_all_days, profile.language), show_alert=True)
        else:
            await callback_query.answer(text=translate(MessageText.no_exercises_to_save, lang=profile.language))


@program_router.message(States.program_manage)
@program_router.message(States.add_exercise_name)
async def add_exercise_name(message: Message, state: FSMContext) -> None:
    profile = user_service.storage.get_current_profile(message.from_user.id)

    link_to_gif = await find_related_gif(message.text)
    shorted_link = await short_url(link_to_gif) if link_to_gif else None

    if link_to_gif:
        gif_file_name = link_to_gif.split("/")[-1]
        user_service.storage.cache_gif_filename(message.text, gif_file_name)

    await message.answer(translate(MessageText.enter_sets, profile.language), reply_markup=sets_number())
    await message.delete()
    await state.update_data(exercise_name=message.text, gif_link=shorted_link)
    await state.set_state(States.enter_sets)


@program_router.callback_query(States.enter_sets)
async def enter_sets(callback_query: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(sets=callback_query.data)
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    await callback_query.answer(translate(MessageText.saved, profile.language))
    data = await state.get_data()
    if data.get("edit_mode"):
        day_index = data.get("day_index")
        selected_exercise = data.get("selected_exercise")
        selected_exercise["sets"] = callback_query.data
        exercises = data.get("exercises", [])
        exercise_index = data.get("exercise_index", 0)
        exercises[day_index][exercise_index] = selected_exercise
        await state.update_data(exercises=exercises)
        await state.set_state(States.program_edit)
        await callback_query.message.answer(
            translate(MessageText.continue_editing, profile.language), reply_markup=program_edit_kb(profile.language)
        )
        await callback_query.message.delete()
        return

    await callback_query.message.answer(translate(MessageText.enter_reps, profile.language), reply_markup=reps_number())
    await callback_query.message.delete()
    await state.set_state(States.enter_reps)


@program_router.callback_query(States.enter_reps)
async def enter_reps(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    await callback_query.answer(translate(MessageText.saved, profile.language))
    data = await state.get_data()
    if data.get("edit_mode"):
        day_index = data.get("day_index")
        selected_exercise = data.get("selected_exercise")
        selected_exercise["reps"] = callback_query.data
        exercises = data.get("exercises", [])
        exercise_index = data.get("exercise_index", 0)
        exercises[day_index][exercise_index] = selected_exercise
        await state.update_data(exercises=exercises)
        await state.set_state(States.program_edit)
        await callback_query.message.answer(
            translate(MessageText.continue_editing, profile.language), reply_markup=program_edit_kb(profile.language)
        )
        await callback_query.message.delete()
        return

    kb = InlineKeyboardBuilder()
    kb.button(text=translate(ButtonText.quit, profile.language), callback_data="skip_weight")
    weight_message = await callback_query.message.answer(
        translate(MessageText.exercise_weight, profile.language), reply_markup=kb.as_markup(one_time_keyboard=True)
    )
    await state.update_data(weight_msg=weight_message.message_id, reps=callback_query.data)
    await callback_query.message.delete()
    await state.set_state(States.exercise_weight)


@program_router.message(States.exercise_weight)
@program_router.callback_query(States.exercise_weight, F.data == "skip_weight")
async def handle_exercise_weight(input_data: CallbackQuery | Message, state: FSMContext) -> None:
    profile = user_service.storage.get_current_profile(input_data.from_user.id)
    data = await state.get_data()
    exercise_name = data.get("exercise_name")
    sets = data.get("sets")
    reps = data.get("reps")
    gif_link = data.get("gif_link")

    if isinstance(input_data, CallbackQuery):
        weight = None
        await input_data.answer()
    else:
        try:
            weight = int(input_data.text)
        except ValueError:
            await input_data.answer(translate(MessageText.invalid_content, lang=profile.language))
            await input_data.delete()
            return

    if data.get("edit_mode"):
        day_index = data.get("day_index", 0)
        selected_exercise = data.get("selected_exercise")
        selected_exercise["weight"] = weight
        exercises = data.get("exercises", [])
        exercise_index = data.get("exercise_index", 0)
        exercises[day_index][exercise_index] = selected_exercise
        await state.update_data(exercises=exercises)
        await state.set_state(States.program_edit)
        await input_data.answer(
            translate(MessageText.continue_editing, profile.language), reply_markup=program_edit_kb(profile.language)
        )
        return

    exercise = Exercise(exercise_name, sets, reps, gif_link, weight)
    await save_exercise(state, exercise, input_data)


@program_router.callback_query(States.workout_survey)
async def workout_results(callback_query: CallbackQuery, state: FSMContext):
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    data = await state.get_data()
    day = data.get("day")
    exercises = data.get("exercises", {})
    day_index = data.get("day_index", 0)

    program = await format_program(exercises, day_index)
    if callback_query.data == "answer_yes":
        await callback_query.answer(translate(MessageText.keep_going, profile.language), show_alert=True)
        client = user_service.storage.get_client_by_id(profile.id)
        coach = user_service.storage.get_coach_by_id(client.assigned_to.pop())
        coach_lang = user_service.storage.get_profile_info_by_key(coach.tg_id, coach.id, "language")
        await send_message(
            recipient=coach,
            text=translate(MessageText.workout_completed, coach_lang).format(name=client.name, program=program),
            state=state,
            reply_markup=workout_feedback(coach_lang, client.id, day),
            include_incoming_message=False,
        )
        await show_main_menu(callback_query.message, profile, state)
        await state.set_state(States.main_menu)
    else:
        await callback_query.answer(translate(MessageText.workout_description, profile.language), show_alert=True)
        await state.set_state(States.workout_description)


@program_router.message(States.workout_description)
async def workout_description(message: Message, state: FSMContext):
    profile = user_service.storage.get_current_profile(message.from_user.id)
    client = user_service.storage.get_client_by_id(profile.id)
    coach = user_service.storage.get_coach_by_id(client.assigned_to.pop())
    coach_lang = user_service.storage.get_profile_info_by_key(coach.tg_id, coach.id, "language")
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
    await state.set_state(States.main_menu)


@program_router.callback_query(States.program_edit)
async def manage_exercises(callback_query: CallbackQuery, state: FSMContext):
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    data = await state.get_data()
    exercises = data.get("exercises", {})
    client_id = data.get("client_id")
    day_index = str(data.get("day_index"))

    if callback_query.data == "exercise_add":
        await state.update_data(exercise_index=len(exercises) + 1, exercises=exercises)
        await callback_query.message.answer(translate(MessageText.enter_exercise, profile.language))
        await state.set_state(States.add_exercise_name)

    elif callback_query.data == "quit":
        await handle_my_clients(callback_query, profile, state)
        return

    elif callback_query.data == "exercise_delete":
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
        if data.get("subscription"):
            subscription_data = user_service.storage.get_subscription(client_id).to_dict()
            subscription_data.update(user=client_id, exercises=exercises)
            await user_service.update_subscription(subscription_data.get("id"), subscription_data)
            user_service.storage.save_subscription(client_id, subscription_data)
        else:
            split_number = user_service.storage.get_program(client_id).split_number
            await user_service.save_program(client_id, exercises, split_number)
        await callback_query.message.answer(translate(MessageText.program_compiled, profile.language))
        await show_main_menu(callback_query.message, profile, state)
        await state.set_state(States.main_menu)
        return

    else:
        if data.get("subscription"):
            subscription = user_service.storage.get_subscription(client_id)
            split_number = len(subscription.workout_days)
        else:
            program = user_service.storage.get_program(client_id)
            split_number = program.split_number

        await state.update_data(split=split_number)
        await handle_program_pagination(state, callback_query)
        return

    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


@program_router.callback_query(States.edit_exercise)
async def select_exercise_to_edit(callback_query: CallbackQuery, state: FSMContext):
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    data = await state.get_data()
    exercises = data.get("exercises")
    exercise_index = int(callback_query.data)
    current_index = 0
    selected_exercise = None

    for _, sublist in enumerate(exercises):
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
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
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
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
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
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    data = await state.get_data()
    days = data.get("days", [])
    day_index = data.get("day_index", 0)
    exercises = data.get("exercises", [])
    await state.update_data(subscription=True)

    if callback_query.data == "back":
        await handle_my_clients(callback_query, profile, state)
        return

    if callback_query.data == "edit":
        program_text = await format_program({days[day_index]: exercises[day_index]}, days[day_index])
        await state.set_state(States.program_edit)
        week_day = get_translated_week_day(profile.language, days[day_index])
        await callback_query.message.answer(
            text=translate(MessageText.program_page, profile.language).format(program=program_text, day=week_day),
            disable_web_page_preview=True,
            reply_markup=program_edit_kb(profile.language),
        )
        await callback_query.message.delete()
        return

    await state.update_data(split=len(days))
    await handle_program_pagination(state, callback_query)


@program_router.callback_query(States.program_view)
async def program_view(callback_query: CallbackQuery, state: FSMContext):
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    data = await state.get_data()
    if callback_query.data == "quit":
        await state.set_state(States.select_service)
        await callback_query.message.answer(
            text=translate(MessageText.select_service, lang=profile.language),
            reply_markup=select_service(profile.language),
        )
        await callback_query.message.delete()
        return

    exercises = data.get("exercises")
    split = data.get("split")
    await state.update_data(exercises=exercises, split=split, day_index=0)
    await handle_program_pagination(state, callback_query)
