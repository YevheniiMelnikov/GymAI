from typing import cast

from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from loguru import logger

from bot.keyboards import (
    workout_feedback_kb,
    select_exercise_kb,
    subscription_view_kb,
    program_view_kb,
    reps_number_kb,
    sets_number_kb,
    program_manage_kb,
)
from bot.states import States
from bot.texts.exercises import exercise_dict
from core.cache import Cache
from core.enums import ClientStatus
from core.services import APIService
from bot.utils.chat import send_message
from bot.utils.exercises import update_exercise_data, save_exercise, format_program, create_exercise
from bot.utils.menus import (
    show_main_menu,
    show_my_clients_menu,
    show_my_subscription_menu,
    show_my_program_menu,
    program_menu_pagination,
    show_exercises_menu,
    show_program_history,
    program_history_pagination,
    show_subscription_history,
    subscription_history_pagination,
    show_subscription_page,
)
from bot.utils.other import (
    short_url,
    delete_messages,
    answer_msg,
    del_msg,
)
from bot.utils.workout_plans import reset_workout_plan, save_workout_plan, next_day_workout_plan
from core.schemas import DayExercises, Profile
from bot.texts import msg_text, btn_text
from core.exceptions import SubscriptionNotFoundError
from core.services.outer import gif_manager

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
        message = cast(Message, callback_query.message)
        assert message is not None
        await show_main_menu(message, profile, state)
        await del_msg(cast(Message | CallbackQuery | None, callback_query))


@workout_router.message(States.workouts_number)
async def workouts_number_choice(message: Message, state: FSMContext):
    if not message.text:
        return

    await delete_messages(state)
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    try:
        workouts_per_week = int(message.text or "0")
        if workouts_per_week < 1 or workouts_per_week > 7:
            raise ValueError
    except (ValueError, TypeError):
        await answer_msg(message, msg_text("invalid_content", profile.language))
        await del_msg(message)
        return

    await state.update_data(split=workouts_per_week, day_index=0, exercises={})
    await answer_msg(message, msg_text("program_guide", profile.language))
    day_1_msg = await answer_msg(
        message,
        msg_text("enter_daily_program", profile.language).format(day=1),
        reply_markup=program_manage_kb(profile.language, workouts_per_week),
    )
    if day_1_msg is not None:
        await state.update_data(chat_id=message.chat.id, message_ids=[day_1_msg.message_id], day_index=0)
    await state.set_state(States.program_manage)


@workout_router.callback_query(States.program_manage)
async def program_manage(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await delete_messages(state)
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    if callback_query.data == "quit":
        await callback_query.answer()
        message = cast(Message, callback_query.message)
        assert message is not None
        await show_main_menu(message, profile, state)
        await del_msg(cast(Message | CallbackQuery | None, callback_query))
    elif callback_query.data == "add_next_day":
        await next_day_workout_plan(callback_query, state)
    elif callback_query.data == "reset":
        await reset_workout_plan(callback_query, state)
    elif callback_query.data == "save":
        await save_workout_plan(callback_query, state, bot)


@workout_router.message(States.program_manage)
@workout_router.message(States.add_exercise_name)
async def set_exercise_name(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    exercise_name = message.text or ""
    link_to_gif = await gif_manager.find_gif(exercise_name, exercise_dict)
    shorted_link = await short_url(link_to_gif) if link_to_gif else None

    if link_to_gif:
        gif_file_name = link_to_gif.split("/")[-1]  # pyrefly: ignore[missing-attribute]
        await Cache.workout.cache_gif_filename(exercise_name, gif_file_name)

    await answer_msg(message, msg_text("enter_sets", profile.language), reply_markup=sets_number_kb())
    await del_msg(message)
    await state.update_data(exercise_name=exercise_name, gif_link=shorted_link)
    await state.set_state(States.enter_sets)


@workout_router.callback_query(States.enter_sets)
async def set_exercise_sets(callback_query: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(sets=callback_query.data)
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    await callback_query.answer(msg_text("saved", profile.language))
    if data.get("edit_mode"):
        message = cast(Message, callback_query.message)
        assert message is not None
        await update_exercise_data(message, state, profile.language, {"sets": callback_query.data})
        await del_msg(cast(Message | CallbackQuery | None, callback_query))
        return

    message = cast(Message, callback_query.message)
    assert message is not None
    await answer_msg(message, msg_text("enter_reps", profile.language), reply_markup=reps_number_kb())
    await del_msg(message)
    await state.set_state(States.enter_reps)


@workout_router.callback_query(States.enter_reps)
async def set_exercise_reps(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    await callback_query.answer(msg_text("saved", profile.language))
    if data.get("edit_mode"):
        message = cast(Message, callback_query.message)
        assert message is not None
        await update_exercise_data(message, state, profile.language, {"reps": callback_query.data})
        await del_msg(cast(Message | CallbackQuery | None, callback_query))
        return

    kb = InlineKeyboardBuilder()
    kb.button(text=btn_text("quit", profile.language), callback_data="skip_weight")
    message = cast(Message, callback_query.message)
    assert message is not None
    weight_message = await answer_msg(
        message,
        msg_text("exercise_weight", profile.language),
        reply_markup=kb.as_markup(one_time_keyboard=True),
    )
    if weight_message is not None:
        await state.update_data(
            chat_id=message.chat.id, message_ids=[weight_message.message_id], reps=callback_query.data
        )
    await del_msg(message)
    await state.set_state(States.exercise_weight)


@workout_router.message(States.exercise_weight)
@workout_router.callback_query(States.exercise_weight)
async def set_exercise_weight(input_data: CallbackQuery | Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    await delete_messages(state)

    if isinstance(input_data, CallbackQuery):
        if input_data.data != "skip_weight":
            return
    else:
        if not input_data.text:
            await input_data.answer(msg_text("invalid_content", profile.language))
            return

    weight: int | None = None
    if isinstance(input_data, CallbackQuery):
        await input_data.answer()
        message = cast(Message, input_data.message)
        assert message is not None
    else:
        try:
            weight = int(input_data.text or "0")
            message = input_data
        except (ValueError, TypeError):
            await input_data.answer(msg_text("invalid_content", profile.language))
            await del_msg(input_data)
            return

    await del_msg(message)
    if data.get("edit_mode"):
        await update_exercise_data(message, state, profile.language, {"weight": weight})
        return

    if data.get("subscription"):
        client_id = cast(int, data.get("client_id"))
        try:
            subscription = await Cache.workout.get_latest_subscription(client_id)
            exercises_to_modify: list[DayExercises] = subscription.exercises
        except SubscriptionNotFoundError:
            logger.info(
                f"Subscription not found for client_id={client_id} in set_exercise_weight – "
                "starting with empty exercises list."
            )
            exercises_to_modify = []
    else:
        raw_exercises = data.get("exercises", [])
        exercises_to_modify = [
            ex if isinstance(ex, DayExercises) else DayExercises.model_validate(ex) for ex in raw_exercises
        ]

    new_exercise = await create_exercise(data, exercises_to_modify, state, weight)
    await save_exercise(state, new_exercise, message, profile)


@workout_router.callback_query(States.workout_survey)
async def send_workout_results(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    day = cast(str, data.get("day", ""))
    day_index = cast(int, data.get("day_index", 0))
    exercises = [DayExercises.model_validate(e) for e in data.get("exercises", [])]
    program = await format_program(exercises, day_index)

    if callback_query.data == "completed":
        await callback_query.answer()
        await callback_query.answer(msg_text("keep_going", profile.language), show_alert=True)

        client = await Cache.client.get_client(profile.id)
        coach = await Cache.coach.get_coach(client.assigned_to.pop())
        coach_profile = await APIService.profile.get_profile(coach.profile)
        coach_lang = cast(str, coach_profile.language)

        await send_message(
            recipient=coach,
            text=msg_text("workout_completed", coach_lang).format(name=client.name, program=program),
            bot=bot,
            state=state,
            reply_markup=workout_feedback_kb(coach_lang, client.id, day),
            include_incoming_message=False,
        )

        message = cast(Message, callback_query.message)
        assert message is not None
        await show_main_menu(message, profile, state)
        await del_msg(cast(Message | CallbackQuery | None, callback_query))
    else:
        await callback_query.answer(msg_text("workout_description", profile.language), show_alert=True)
        await state.set_state(States.workout_description)


@workout_router.message(States.workout_description)
async def workout_description(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    client = await Cache.client.get_client(profile.id)
    coach = await Cache.coach.get_coach(client.assigned_to.pop())
    coach_profile = await APIService.profile.get_profile(coach.profile)
    coach_lang = cast(str, coach_profile.language)

    day_index = cast(int, data.get("day_index"))
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
        bot=bot,
        state=state,
        reply_markup=workout_feedback_kb(coach_lang, client.id, cast(str, data.get("day", ""))),
        include_incoming_message=False,
    )

    await answer_msg(message, msg_text("keep_going", profile.language))
    await show_main_menu(message, profile, state)
    await del_msg(message)


@workout_router.callback_query(States.program_edit)
async def manage_exercises(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    exercises = [DayExercises.model_validate(e) for e in data.get("exercises", [])]
    client_id = cast(int, data.get("client_id"))
    day_index = str(data.get("day_index", 0))

    day_data = next((d for d in exercises if d.day == day_index), None)

    if callback_query.data == "exercise_add":
        await callback_query.answer()
        exercise_msg = await answer_msg(
            cast(Message, callback_query.message), msg_text("enter_exercise", profile.language)
        )
        if not day_data:
            exercises.append(DayExercises(day=day_index, exercises=[]))
        else:
            await state.update_data(exercise_index=len(day_data.exercises))
        await state.update_data(
            exercises=exercises,
            message_ids=[exercise_msg.message_id] if exercise_msg else [],
            chat_id=cast(Message, callback_query.message).chat.id,
            edit_mode=False,
        )
        await state.set_state(States.add_exercise_name)

    elif callback_query.data == "quit":
        await callback_query.answer()
        await show_my_clients_menu(callback_query, profile, state)
        return

    elif callback_query.data == "reset":
        await reset_workout_plan(callback_query, state)

    elif callback_query.data == "exercise_delete":
        await callback_query.answer()
        if day_data:
            await answer_msg(
                cast(Message, callback_query.message),
                msg_text("select_exercise", profile.language),
                reply_markup=select_exercise_kb(day_data.exercises),
            )
        else:
            await answer_msg(cast(Message, callback_query.message), msg_text("no_exercises_found", profile.language))
        await state.set_state(States.delete_exercise)

    elif callback_query.data == "exercise_edit":
        await state.update_data(edit_mode=True)
        if day_data:
            await answer_msg(
                cast(Message, callback_query.message),
                msg_text("select_exercise", profile.language),
                reply_markup=select_exercise_kb(day_data.exercises),
            )
        else:
            await answer_msg(cast(Message, callback_query.message), msg_text("no_exercises_found", profile.language))
        await state.set_state(States.edit_exercise)

    elif callback_query.data == "finish_editing":
        await callback_query.answer(btn_text("done", profile.language))
        client = await Cache.client.get_client(client_id)
        client_profile = await APIService.profile.get_profile(client.profile)
        client_lang = cast(str, client_profile.language)

        if data.get("subscription"):
            if subscription := await Cache.workout.get_latest_subscription(client_id):
                subscription_data = subscription.model_dump()
                subscription_data.update(client_profile=client_id, exercises=exercises)
                await APIService.workout.update_subscription(
                    cast(int, subscription_data.get("id", 0)), subscription_data
                )
                await Cache.workout.update_subscription(
                    client_id=client_id,
                    updates=dict(exercises=exercises, client_profile=client_id),
                )
                await Cache.payment.reset_status(client_id, "subscription")
                await send_message(
                    recipient=client,
                    text=msg_text("new_program", client_lang),
                    bot=bot,
                    state=state,
                    reply_markup=subscription_view_kb(client_lang),
                    include_incoming_message=False,
                )
        else:
            current_program = await Cache.workout.get_program(client_id)
            program_text = await format_program(exercises, 0)
            if current_program is not None:
                if program := await APIService.workout.save_program(
                    client_id, exercises, current_program.split_number, current_program.wishes
                ):
                    program_data = program.model_dump()
                    program_data.update(workout_type=current_program.workout_type)
                    await Cache.workout.save_program(client_id, program_data)
                    await Cache.payment.reset_status(client_id, "program")
            await send_message(
                recipient=client,
                text=msg_text("new_program", client_lang),
                bot=bot,
                state=state,
                include_incoming_message=False,
            )
            await send_message(
                recipient=client,
                text=msg_text("program_page", client_lang).format(program=program_text, day=1),
                bot=bot,
                state=state,
                reply_markup=program_view_kb(client_lang),
                include_incoming_message=False,
            )

        await Cache.client.update_client(client_id, dict(status=ClientStatus.default))
        message = cast(Message, callback_query.message)
        assert message is not None
        await show_main_menu(message, profile, state)

    else:
        if data.get("subscription"):
            subscription = await Cache.workout.get_latest_subscription(client_id)
            split_number = len(subscription.workout_days) if subscription else 1
        else:
            program = await Cache.workout.get_program(client_id)
            split_number = program.split_number if program else 1

        await state.update_data(split=split_number)
        await program_menu_pagination(state, callback_query)

    await del_msg(cast(Message | CallbackQuery | None, callback_query))


@workout_router.callback_query()
async def show_history(callback_query: CallbackQuery, state: FSMContext) -> None:
    if callback_query.data != "history":
        return
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    current_state = await state.get_state()
    if current_state == States.program_view.state:
        await show_program_history(callback_query, profile, state)
    elif current_state == States.show_subscription.state:
        await show_subscription_history(callback_query, profile, state)


@workout_router.callback_query(States.program_history)
async def program_history_nav(callback_query: CallbackQuery, state: FSMContext) -> None:
    data_str = callback_query.data or ""
    if data_str == "back":
        data = await state.get_data()
        await show_exercises_menu(callback_query, state, Profile.model_validate(data["profile"]))
        return
    if "_" not in data_str:
        lang = (await Cache.profile.get_profile(callback_query.from_user.id)).language
        await callback_query.answer(msg_text("out_of_range", lang))
        return
    _, index_str = data_str.rsplit("_", 1)
    try:
        index = int(index_str)
    except ValueError:
        lang = (await Cache.profile.get_profile(callback_query.from_user.id)).language
        await callback_query.answer(msg_text("out_of_range", lang))
        return
    profile = await Cache.profile.get_profile(callback_query.from_user.id)
    assert profile is not None
    await program_history_pagination(callback_query, profile, index, state)


@workout_router.callback_query(States.subscription_history)
async def subscription_history_nav(callback_query: CallbackQuery, state: FSMContext) -> None:
    data_str = callback_query.data or ""
    if data_str == "back":
        subscription = await Cache.workout.get_latest_subscription(callback_query.from_user.id)
        await show_subscription_page(callback_query, state, subscription)
        return
    if "_" not in data_str:
        lang = (await Cache.profile.get_profile(callback_query.from_user.id)).language
        await callback_query.answer(msg_text("out_of_range", lang))
        return
    _, index_str = data_str.rsplit("_", 1)
    try:
        index = int(index_str)
    except ValueError:
        lang = (await Cache.profile.get_profile(callback_query.from_user.id)).language
        await callback_query.answer(msg_text("out_of_range", lang))
        return
    profile = await Cache.profile.get_profile(callback_query.from_user.id)
    assert profile is not None
    await subscription_history_pagination(callback_query, profile, index, state)
