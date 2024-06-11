from contextlib import suppress

import loguru
from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import program_manage_menu, program_view_kb
from bot.states import States
from common.functions import find_related_gif, format_program, send_message, show_main_menu
from common.user_service import user_service
from common.utils import short_url
from texts.text_manager import ButtonText, MessageText, translate

program_router = Router()
logger = loguru.logger


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
async def adding_exercise(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile = user_service.storage.get_current_profile(message.from_user.id)
    exercises_by_day = data.get("exercises_by_day", {})
    completed_days = data.get("completed_days", 0)
    current_day = completed_days + 1

    if link_to_gif := await find_related_gif(message.text):
        shorted_link = await short_url(link_to_gif)
        exercise_entry = (message.text, shorted_link)
    else:
        exercise_entry = (message.text,)

    day_key = str(current_day)
    if day_key not in exercises_by_day:
        exercises_by_day[day_key] = []

    exercises_by_day[day_key].append(exercise_entry)

    if link_to_gif:
        gif_file_name = link_to_gif.split("/")[-1]
        user_service.storage.cache_gif_filename(message.text, gif_file_name)

    program = await format_program(exercises_by_day, current_day)

    if "program_msg" in data:
        with suppress(TelegramBadRequest):
            await message.bot.delete_message(message.chat.id, data["program_msg"])

    for msg_key in ["del_msg", "exercise_msg", "program_msg", "day_1_msg"]:
        if del_msg := data.get(msg_key):
            with suppress(TelegramBadRequest):
                await message.bot.delete_message(message.chat.id, del_msg)

    exercise_msg = await message.answer(translate(MessageText.enter_exercise, profile.language))
    program_msg = await exercise_msg.answer(
        text=translate(MessageText.program_page, profile.language).format(program=program, day=current_day),
        reply_markup=program_manage_menu(profile.language),
        disable_web_page_preview=True,
    )

    await state.update_data(
        exercise_msg=exercise_msg.message_id,
        program_msg=program_msg.message_id,
        exercises_by_day=exercises_by_day,
    )
    with suppress(TelegramBadRequest):
        await message.delete()


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


@program_router.callback_query(States.subscription_manage)  # TODO: IMPLEMENT
async def manage_subscription(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer("will be added soon")
