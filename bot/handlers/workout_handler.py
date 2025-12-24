from contextlib import suppress
from typing import cast
from uuid import uuid4

from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from loguru import logger

from bot.keyboards import (
    select_exercise_kb,
    subscription_view_kb,
    reps_number_kb,
    sets_number_kb,
    program_manage_kb,
)
from bot.states import States
from bot.texts.exercises import exercise_dict
from core.cache import Cache
from core.enums import ProfileStatus
from core.services import APIService
from bot.utils.chat import send_message
from bot.utils.exercises import update_exercise_data, save_exercise, create_exercise
from bot.utils.menus import (
    show_main_menu,
    program_menu_pagination,
    subscription_history_pagination,
    show_subscription_page,
    start_program_flow,
    start_subscription_flow,
)
from bot.utils.other import (
    short_url,
)
from bot.utils.bot import del_msg, answer_msg, delete_messages
from bot.utils.workout_plans import reset_workout_plan, save_workout_plan, next_day_workout_plan
from bot.utils.ai_coach import enqueue_ai_question
from bot.utils.ask_ai import prepare_ask_ai_request
from core.schemas import DayExercises, Profile
from bot.texts import ButtonText, MessageText, translate
from core.exceptions import AskAiPreparationError, SubscriptionNotFoundError
from config.app_settings import settings
from core.services import get_gif_manager

workout_router = Router()


@workout_router.callback_query(States.ask_ai_question)
async def ask_ai_question_navigation(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        await callback_query.answer()
        await del_msg(callback_query)
        return
    profile = Profile.model_validate(profile_data)
    if callback_query.data != "ask_ai_back":
        await callback_query.answer()
        return

    await callback_query.answer()
    await state.update_data(ask_ai_prompt_id=None, ask_ai_prompt_chat_id=None, ask_ai_cost=None)
    await del_msg(callback_query)
    if callback_query.message and isinstance(callback_query.message, Message):
        await show_main_menu(callback_query.message, profile, state)
    else:
        await state.set_state(States.main_menu)


@workout_router.message(States.ask_ai_question)
async def process_ask_ai_question(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        await answer_msg(message, translate(MessageText.unexpected_error, settings.DEFAULT_LANG))
        await del_msg(message)
        return

    profile = Profile.model_validate(profile_data)
    lang = profile.language or settings.DEFAULT_LANG

    try:
        ask_ai_prompt_id = data.get("ask_ai_prompt_id")
        ask_ai_prompt_chat_id = data.get("ask_ai_prompt_chat_id")
        if ask_ai_prompt_id:
            chat_id = int(ask_ai_prompt_chat_id or message.chat.id)
            with suppress(TelegramBadRequest):
                await bot.delete_message(chat_id, int(ask_ai_prompt_id))
            await state.update_data(ask_ai_prompt_id=None, ask_ai_prompt_chat_id=None)

        try:
            preparation = await prepare_ask_ai_request(
                message=message,
                profile=profile,
                state_data=data,
                bot=bot,
            )
        except AskAiPreparationError as error:
            try:
                message_key = MessageText[error.message_key]
            except KeyError as exc:
                raise ValueError(f"Unknown message key {error.message_key}") from exc
            response = translate(message_key, lang)
            if error.params:
                response = response.format(**error.params)
            await answer_msg(message, response)
            if error.delete_message:
                await del_msg(message)
            return

        user_profile = preparation.profile
        question_text = preparation.prompt
        cost = preparation.cost
        image_base64 = preparation.image_base64
        image_mime = preparation.image_mime

        request_id = uuid4().hex
        logger.info(f"event=ask_ai_enqueue request_id={request_id} profile_id={profile.id}")

        queued = await enqueue_ai_question(
            profile=user_profile,
            prompt=question_text,
            language=profile.language,
            request_id=request_id,
            cost=cost,
            image_base64=image_base64,
            image_mime=image_mime,
        )

        if not queued:
            logger.error(f"event=ask_ai_enqueue_failed request_id={request_id} profile_id={profile.id}")
            await answer_msg(
                message,
                translate(MessageText.coach_agent_error, lang).format(tg=settings.TG_SUPPORT_CONTACT),
            )
            return

        await answer_msg(message, translate(MessageText.request_in_progress, lang))

        state_payload: dict[str, object] = {
            "profile": user_profile.model_dump(mode="json"),
            "last_request_id": request_id,
            "ask_ai_cost": cost,
            "ask_ai_prompt_id": None,
            "ask_ai_prompt_chat_id": None,
            "ask_ai_question_message_id": message.message_id,
        }
        await show_main_menu(message, profile, state, delete_source=False)
        await state.update_data(**state_payload)
    except Exception:
        logger.exception(f"event=ask_ai_process_failed profile_id={profile.id}")
        await answer_msg(
            message,
            translate(MessageText.coach_agent_error, lang).format(tg=settings.TG_SUPPORT_CONTACT),
        )


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
        await answer_msg(message, translate(MessageText.invalid_content, profile.language))
        await del_msg(message)
        return

    await state.update_data(split=workouts_per_week, day_index=0, exercises={})
    await answer_msg(message, translate(MessageText.program_guide, profile.language))
    day_1_msg = await answer_msg(
        message,
        translate(MessageText.enter_daily_program, profile.language).format(day=1),
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
    elif callback_query.data == "toggle_set":
        if data.get("set_mode"):
            await state.update_data(set_mode=False, set_id=None)
            await callback_query.answer(translate(MessageText.set_mode_off, profile.language))
        else:
            current_id = int(data.get("current_set_id", 0)) + 1
            await state.update_data(set_mode=True, set_id=current_id, current_set_id=current_id)
            await callback_query.answer(translate(MessageText.set_mode_on, profile.language))
    elif callback_query.data == "reset":
        await reset_workout_plan(callback_query, state)
    elif callback_query.data == "save":
        await save_workout_plan(callback_query, state, bot)


@workout_router.callback_query(States.program_action_choice)
async def program_action_choice(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    message = callback_query.message
    if message is None or not isinstance(message, Message):
        return
    cb_data = callback_query.data or ""

    if cb_data == "back":
        await callback_query.answer()
        await show_main_menu(message, profile, state)

    elif cb_data == "new_program":
        await callback_query.answer()
        await start_program_flow(callback_query, profile, state)
        await del_msg(message)
        return

    await del_msg(message)


@workout_router.callback_query(States.subscription_action_choice)
async def subscription_action_choice(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    message = callback_query.message
    if message is None or not isinstance(message, Message):
        return
    cb_data = callback_query.data or ""

    if cb_data == "new_subscription":
        await callback_query.answer()
        await start_subscription_flow(callback_query, profile, state)
        await del_msg(message)
        return

    if cb_data == "back":
        await callback_query.answer()
        await show_main_menu(message, profile, state)
        return


@workout_router.message(States.program_manage)
@workout_router.message(States.add_exercise_name)
async def set_exercise_name(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    exercise_name = message.text or ""
    gif_manager = get_gif_manager()
    link_to_gif = await gif_manager.find_gif(exercise_name, exercise_dict)
    shorted_link = await short_url(link_to_gif) if link_to_gif else None

    if link_to_gif:
        gif_file_name = link_to_gif.split("/")[-1]  # pyrefly: ignore[missing-attribute]
        await Cache.workout.cache_gif_filename(exercise_name, gif_file_name)

    await answer_msg(message, translate(MessageText.enter_sets, profile.language), reply_markup=sets_number_kb())
    await del_msg(message)
    await state.update_data(exercise_name=exercise_name, gif_link=shorted_link)
    await state.set_state(States.enter_sets)


@workout_router.callback_query(States.enter_sets)
async def set_exercise_sets(callback_query: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(sets=callback_query.data)
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    await callback_query.answer(translate(MessageText.saved, profile.language))
    if data.get("edit_mode"):
        message = cast(Message, callback_query.message)
        assert message is not None
        await update_exercise_data(message, state, profile.language, {"sets": callback_query.data})
        await del_msg(cast(Message | CallbackQuery | None, callback_query))
        return

    message = cast(Message, callback_query.message)
    assert message is not None
    await answer_msg(message, translate(MessageText.enter_reps, profile.language), reply_markup=reps_number_kb())
    await del_msg(message)
    await state.set_state(States.enter_reps)


@workout_router.callback_query(States.enter_reps)
async def set_exercise_reps(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    await callback_query.answer(translate(MessageText.saved, profile.language))
    if data.get("edit_mode"):
        message = cast(Message, callback_query.message)
        assert message is not None
        await update_exercise_data(message, state, profile.language, {"reps": callback_query.data})
        await del_msg(cast(Message | CallbackQuery | None, callback_query))
        return

    kb = InlineKeyboardBuilder()
    kb.button(text=translate(ButtonText.quit, profile.language), callback_data="skip_weight")
    message = cast(Message, callback_query.message)
    assert message is not None
    weight_message = await answer_msg(
        message,
        translate(MessageText.exercise_weight, profile.language),
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
            await input_data.answer(translate(MessageText.invalid_content, profile.language))
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
            await input_data.answer(translate(MessageText.invalid_content, profile.language))
            await del_msg(input_data)
            return

    await del_msg(message)

    if data.get("edit_mode"):
        await update_exercise_data(message, state, profile.language, {"weight": weight})
        return

    if data.get("subscription"):
        profile_id = cast(int, data.get("profile_id"))
        try:
            subscription = await Cache.workout.get_latest_subscription(profile_id)
            exercises_to_modify: list[DayExercises] = subscription.exercises
        except SubscriptionNotFoundError:
            logger.info(
                f"Subscription not found for profile_id={profile_id} "
                "in set_exercise_weight – starting with empty exercises list."
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
    if callback_query.data == "completed":
        await callback_query.answer()
        await callback_query.answer(translate(MessageText.keep_going, profile.language), show_alert=True)
        message = cast(Message, callback_query.message)
        assert message is not None
        await show_main_menu(message, profile, state)
        await del_msg(cast(Message | CallbackQuery | None, callback_query))
    else:
        await callback_query.answer(translate(MessageText.workout_description, profile.language), show_alert=True)


@workout_router.callback_query(States.program_edit)
async def manage_exercises(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    exercises = [DayExercises.model_validate(e) for e in data.get("exercises", [])]
    profile_id = cast(int, data.get("profile_id"))
    day_index = str(data.get("day_index", 0))

    day_data = next((d for d in exercises if d.day == day_index), None)

    if callback_query.data == "exercise_add":
        await callback_query.answer()
        exercise_msg = await answer_msg(
            cast(Message, callback_query.message), translate(MessageText.enter_exercise, profile.language)
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

    elif callback_query.data == "toggle_set":
        if data.get("set_mode"):
            await state.update_data(set_mode=False, set_id=None)
            await callback_query.answer(translate(MessageText.set_mode_off, profile.language))
        else:
            current_id = int(data.get("current_set_id", 0)) + 1
            await state.update_data(set_mode=True, set_id=current_id, current_set_id=current_id)
            await callback_query.answer(translate(MessageText.set_mode_on, profile.language))

    elif callback_query.data == "quit":
        await callback_query.answer()
        message = cast(Message, callback_query.message)
        assert message is not None
        await show_main_menu(message, profile, state)
        return

    elif callback_query.data == "reset":
        await reset_workout_plan(callback_query, state)

    elif callback_query.data == "exercise_delete":
        await callback_query.answer()
        if day_data:
            await answer_msg(
                cast(Message, callback_query.message),
                translate(MessageText.select_exercise, profile.language),
                reply_markup=select_exercise_kb(day_data.exercises),
            )
        else:
            await answer_msg(
                cast(Message, callback_query.message), translate(MessageText.no_exercises_found, profile.language)
            )
        await state.set_state(States.delete_exercise)

    elif callback_query.data == "toggle_drop_set":
        await callback_query.answer()
        if day_data:
            await answer_msg(
                cast(Message, callback_query.message),
                translate(MessageText.select_exercise, profile.language),
                reply_markup=select_exercise_kb(day_data.exercises),
            )
        else:
            await answer_msg(
                cast(Message, callback_query.message), translate(MessageText.no_exercises_found, profile.language)
            )
        await state.set_state(States.toggle_drop_set)

    elif callback_query.data == "exercise_edit":
        await state.update_data(edit_mode=True)
        if day_data:
            await answer_msg(
                cast(Message, callback_query.message),
                translate(MessageText.select_exercise, profile.language),
                reply_markup=select_exercise_kb(day_data.exercises),
            )
        else:
            await answer_msg(
                cast(Message, callback_query.message), translate(MessageText.no_exercises_found, profile.language)
            )
        await state.set_state(States.edit_exercise)

    elif callback_query.data == "finish_editing":
        await callback_query.answer(translate(ButtonText.done, profile.language))
        profile_record = await Cache.profile.get_record(profile_id)
        profile_data = await APIService.profile.get_profile(profile_record.id)
        client_lang = cast(str, profile_data.language)

        if data.get("subscription"):
            if subscription := await Cache.workout.get_latest_subscription(profile_id):
                subscription_data = subscription.model_dump()
                subscription_data.update(profile=profile_id, exercises=exercises)
                await APIService.workout.update_subscription(
                    cast(int, subscription_data.get("id", 0)), subscription_data
                )
                await Cache.workout.update_subscription(
                    profile_id, updates=dict(exercises=exercises, profile=profile_id)
                )
                await Cache.payment.reset_status(profile_id, "subscription")
                await send_message(
                    recipient=profile_record,
                    text=translate(MessageText.program_updated, client_lang).format(bot_name=settings.BOT_NAME),
                    bot=bot,
                    state=state,
                    reply_markup=subscription_view_kb(client_lang),
                    include_incoming_message=False,
                )
        else:
            current_program = await Cache.workout.get_latest_program(profile_id)
            if current_program is not None:
                if program := await APIService.workout.save_program(
                    profile_id, exercises, current_program.split_number, current_program.wishes
                ):
                    program_data = program.model_dump()
                    program_data.update(workout_location=current_program.workout_location)
                    await Cache.workout.save_program(profile_id, program_data)
                    await Cache.payment.reset_status(profile_id, "program")
            await send_message(
                recipient=profile_record,
                text=translate(MessageText.program_updated, client_lang).format(bot_name=settings.BOT_NAME),
                bot=bot,
                state=state,
                include_incoming_message=False,
            )

        await Cache.profile.update_record(profile_record.id, dict(status=ProfileStatus.completed))
        message = cast(Message, callback_query.message)
        assert message is not None
        await show_main_menu(message, profile, state)

    else:
        if data.get("subscription"):
            subscription = await Cache.workout.get_latest_subscription(profile_id)
            split_number = len(subscription.workout_days) if subscription else 1
        else:
            program = await Cache.workout.get_latest_program(profile_id)
            split_number = program.split_number if program else 1

        await state.update_data(split=split_number)
        await program_menu_pagination(state, callback_query)

    await del_msg(cast(Message | CallbackQuery | None, callback_query))


@workout_router.callback_query(States.toggle_drop_set)
async def toggle_drop_set_callback(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    exercises = [DayExercises.model_validate(e) for e in data.get("exercises", [])]
    day_index = str(data.get("day_index", 0))
    day_data = next((d for d in exercises if d.day == day_index), None)
    if not day_data:
        await callback_query.answer(translate(MessageText.no_exercises_found, profile.language))
        await state.set_state(States.program_edit)
        return

    try:
        ex_index = int(callback_query.data or 0)
    except ValueError:
        await callback_query.answer(translate(MessageText.out_of_range, profile.language))
        return

    if ex_index < 0 or ex_index >= len(day_data.exercises):
        await callback_query.answer(translate(MessageText.out_of_range, profile.language))
        return

    exercise = day_data.exercises[ex_index]
    await state.update_data(selected_day_index=int(day_index), selected_ex_index=ex_index)
    await update_exercise_data(
        cast(Message, callback_query.message),
        state,
        profile.language,
        {"drop_set": not exercise.drop_set},
    )


@workout_router.callback_query(States.program_view)
async def view_program(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])

    if callback_query.data == "quit":
        await show_main_menu(cast(Message, callback_query.message), profile, state)
        await del_msg(cast(Message | CallbackQuery | None, callback_query))
        await callback_query.answer()
        return

    await program_menu_pagination(state, callback_query)


@workout_router.callback_query(States.subscription_history)
async def subscription_history_nav(callback_query: CallbackQuery, state: FSMContext) -> None:
    cb_data = callback_query.data or ""
    if cb_data == "back":
        data = await state.get_data()
        profile = Profile.model_validate(data.get("profile"))
        profile_record = await Cache.profile.get_record(profile.id)
        subscription = await Cache.workout.get_latest_subscription(profile_record.id)
        await show_subscription_page(callback_query, state, subscription)
        return

    if "_" not in cb_data:
        lang = (await Cache.profile.get_profile(callback_query.from_user.id)).language
        await callback_query.answer(translate(MessageText.out_of_range, lang))
        return

    _, index_str = cb_data.rsplit("_", 1)
    try:
        index = int(index_str)
    except ValueError:
        lang = (await Cache.profile.get_profile(callback_query.from_user.id)).language
        await callback_query.answer(translate(MessageText.out_of_range, lang))
        return

    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    assert profile is not None
    await subscription_history_pagination(callback_query, profile, index, state)
