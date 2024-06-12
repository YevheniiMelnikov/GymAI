from contextlib import suppress

import loguru
from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards import (
    program_manage_menu,
    program_view_kb,
    choose_payment_options,
    select_service,
    sets_number,
    reps_number,
)
from bot.states import States
from common.functions import (
    find_related_gif,
    format_program,
    send_message,
    show_main_menu,
    show_subscription_page,
    save_exercise,
)
from common.user_service import user_service
from common.utils import short_url
from texts.text_manager import ButtonText, MessageText, translate

program_router = Router()
logger = loguru.logger


@program_router.callback_query(States.select_service)
async def program_type(callback_query: CallbackQuery, state: FSMContext):
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text=translate(ButtonText.back, profile.language), callback_data="back")
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
                program = await format_program(exercises, 1)
                await callback_query.message.answer(
                    text=translate(MessageText.program_page, lang=profile.language).format(program=program, day=1),
                    reply_markup=kb.as_markup(one_time_keyboard=True),
                    disable_web_page_preview=True,
                )
                with suppress(TelegramBadRequest):
                    await callback_query.message.delete()
                await state.set_state(States.program_view)
            else:
                await callback_query.answer(translate(MessageText.program_not_ready, profile.language), show_alert=True)

            await show_subscription_page(callback_query, state, subscription)

    elif callback_query.data == "program":
        if exercises := user_service.storage.get_program(profile.id):
            program_paid = user_service.storage.check_program_payment(profile.id)
            if program_paid:
                await callback_query.answer(translate(MessageText.program_not_ready, profile.language), show_alert=True)
                return
            else:
                program = await format_program(exercises.exercises_by_day, 1)
                await callback_query.message.answer(
                    text=translate(MessageText.program_page, lang=profile.language).format(program=program, day=1),
                    reply_markup=program_view_kb(profile.language),
                    disable_web_page_preview=True,
                )
                with suppress(TelegramBadRequest):
                    await callback_query.message.delete()
                await state.set_state(States.program_view)
        else:
            program_img = f"https://storage.googleapis.com/bot_payment_options/program_{profile.language}.jpeg"
            await callback_query.message.answer_photo(
                photo=program_img,
                reply_markup=choose_payment_options(profile.language, "program"),
            )
            await state.set_state(States.payment_choice)
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

    await state.update_data(split=workouts_per_week, completed_days=0, exercises_by_day={})
    await message.answer(text=translate(MessageText.program_guide, lang=profile.language))
    day_1_msg = await message.answer(
        translate(MessageText.enter_daily_program, profile.language).format(day=1),
        reply_markup=program_manage_menu(profile.language),
    )
    with suppress(TelegramBadRequest):
        await message.delete()
    await state.update_data(day_1_msg=day_1_msg.message_id)
    await state.set_state(States.program_manage)


@program_router.callback_query(States.program_manage)
async def program_manage(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    data = await state.get_data()
    split_number = data.get("split")
    client_id = data.get("client_id")
    completed_days = data.get("completed_days", 0)
    exercises_by_day = data.get("exercises_by_day", {})

    if callback_query.data == "quit":
        await show_main_menu(callback_query.message, profile, state)
        await state.set_state(States.main_menu)

    elif callback_query.data == "next":
        if exercises_by_day:
            if completed_days + 1 < split_number:
                completed_days += 1
                current_day = completed_days + 1
                await state.update_data(completed_days=completed_days)
                await callback_query.answer("⏭")

                if "program_msg" in data:
                    with suppress(TelegramBadRequest):
                        await callback_query.message.bot.delete_message(
                            callback_query.message.chat.id, data["program_msg"]
                        )

                program = await format_program(exercises_by_day, current_day)
                program_msg = await callback_query.message.answer(
                    text=translate(MessageText.program_page, profile.language).format(program=program, day=current_day),
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
        if await user_service.delete_program(str(client_id)):
            logger.info(f"Program for profile_id {client_id} deleted from DB")
            user_service.storage.delete_program(str(client_id))
        await state.clear()
        await callback_query.message.answer(translate(MessageText.enter_daily_program, profile.language).format(day=1))
        await state.update_data(client_id=client_id, exercises_by_day={}, completed_days=0)
        await state.set_state(States.program_manage)
        with suppress(TelegramBadRequest):
            await callback_query.message.delete()

    elif callback_query.data == "save":
        if exercises_by_day:
            if completed_days == split_number - 1:
                await callback_query.answer(text=translate(MessageText.saved, lang=profile.language))
                await user_service.save_program(str(client_id), exercises_by_day, split_number)
                client = user_service.storage.get_client_by_id(client_id)
                exercises = user_service.storage.get_program(str(client_id)).exercises_by_day
                program = await format_program(exercises, 1)
                client_lang = user_service.storage.get_profile_info_by_key(client.tg_id, client.id, "language")

                await send_message(
                    recipient=client,
                    text=translate(MessageText.new_program, lang=client_lang),
                    state=state,
                    include_incoming_message=False,
                )
                await send_message(
                    recipient=client,
                    text=translate(MessageText.program_page, lang=profile.language).format(program=program, day=1),
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
async def add_exercise_name(message: Message, state: FSMContext) -> None:
    profile = user_service.storage.get_current_profile(message.from_user.id)
    exercise_name = message.text

    link_to_gif = await find_related_gif(exercise_name)
    shorted_link = await short_url(link_to_gif) if link_to_gif else None

    if link_to_gif:
        gif_file_name = link_to_gif.split("/")[-1]
        user_service.storage.cache_gif_filename(exercise_name, gif_file_name)

    await message.answer(translate(MessageText.enter_sets, profile.language), reply_markup=sets_number())
    await message.delete()
    await state.update_data(exercise_name=exercise_name, gif_link=shorted_link)
    await state.set_state(States.enter_sets)


@program_router.callback_query(States.enter_sets)
async def enter_sets(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    await callback_query.message.answer(translate(MessageText.enter_reps, profile.language), reply_markup=reps_number())
    await callback_query.message.delete()
    await state.update_data(sets=callback_query.data)
    await state.set_state(States.enter_reps)


@program_router.callback_query(States.enter_reps)
async def enter_reps(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text=translate(ButtonText.quit, profile.language), callback_data="quit")
    await callback_query.message.answer(
        translate(MessageText.exercise_weight, profile.language), reply_markup=kb.as_markup(one_time_keyboard=True)
    )
    await callback_query.message.delete()
    await state.update_data(reps=callback_query.data)
    await state.set_state(States.exercise_weight)


@program_router.message(States.exercise_weight)
@program_router.callback_query(States.exercise_weight, F.data == "quit")
async def handle_exercise_weight(input_data: CallbackQuery | Message, state: FSMContext) -> None:
    data = await state.get_data()
    completed_days = data.get("completed_days", 0)
    current_day = completed_days + 1
    exercise_name = data.get("exercise_name")
    sets = data.get("sets")
    reps = data.get("reps")
    gif_link = data.get("gif_link")

    if isinstance(input_data, CallbackQuery):
        weight = None
        await input_data.answer()
    else:
        weight = input_data.text

    exercise_entry = (exercise_name, sets, reps, weight, gif_link)
    await save_exercise(state, current_day, exercise_entry, input_data)
    with suppress(TelegramBadRequest):
        if isinstance(input_data, Message):
            await input_data.delete()
        else:
            await input_data.message.delete()


@program_router.callback_query(States.workout_survey)
async def workout_results(callback_query: CallbackQuery, state: FSMContext):
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    if callback_query.data == "answer_yes":
        await callback_query.answer(translate(MessageText.keep_going, profile.language), show_alert=True)
        client = user_service.storage.get_client_by_id(profile.id)
        coach = user_service.storage.get_coach_by_id(client.assigned_to.pop())
        await send_message(
            recipient=coach,
            text="text",
            state=state,
            reply_markup=None,  # TODO: ADD KEYBOARD
            include_incoming_message=False,
        )
    else:
        await callback_query.answer(translate(MessageText.workout_description, profile.language), show_alert=True)
        await state.set_state(States.workout_description)


@program_router.message(States.workout_description)
async def workout_description(message: Message, state: FSMContext):
    profile = user_service.storage.get_current_profile(message.from_user.id)
    client = user_service.storage.get_client_by_id(profile.id)
    coach = user_service.storage.get_coach_by_id(client.assigned_to.pop())
    await send_message(
        recipient=coach,
        text=message.text,  # TODO: FORMAT
        state=state,
        reply_markup=None,  # TODO: ADD KEYBOARD
        include_incoming_message=False,
    )
    await message.answer(translate(MessageText.keep_going, profile.language))
    await show_main_menu(message, profile, state)
    await state.set_state(States.main_menu)


@program_router.callback_query(States.program_view)  # TODO: DON'T REPEAT YOURSELF
async def program_view(callback_query: CallbackQuery, state: FSMContext):
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    if callback_query.data == "quit":
        await state.set_state(States.select_service)
        await callback_query.message.answer(
            text=translate(MessageText.select_service, lang=profile.language),
            reply_markup=select_service(profile.language),
        )
        await callback_query.message.delete()
        return

    data = await state.get_data()
    program = user_service.storage.get_program(str(profile.id))
    current_day = int(data.get("current_day", 1))

    if callback_query.data == "prev_day":
        new_day = current_day - 1
    else:
        new_day = current_day + 1

    if new_day < 1 or new_day > program.split_number:
        await callback_query.answer(translate(MessageText.out_of_range, profile.language))

        if new_day < 1:
            new_day = 1
        elif new_day > program.split_number:
            new_day = program.split_number

        await state.update_data(current_day=new_day)
        return

    program_text = await format_program(program.exercises_by_day, new_day)
    await callback_query.message.edit_text(
        text=translate(MessageText.program_page, profile.language).format(program=program_text, day=new_day),
        reply_markup=program_view_kb(profile.language),
        disable_web_page_preview=True,
    )
    await state.update_data(current_day=new_day)
    await callback_query.answer()


@program_router.callback_query(States.subscription_manage)
async def manage_subscription(callback_query: CallbackQuery, state: FSMContext):
    pass
