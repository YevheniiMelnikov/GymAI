import asyncio
from contextlib import suppress
from datetime import datetime

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.keyboards import program_edit_kb, program_manage_kb, program_view_kb, subscription_view_kb
from bot.states import States
from core.cache_manager import CacheManager
from core.services.workout_service import WorkoutService
from functions.chat import send_message
from functions.menus import show_main_menu
from functions.profiles import get_user_profile
from functions.text_utils import format_program, get_translated_week_day
from functions.utils import delete_messages
from core.models import Profile
from core.services.profile_service import ProfileService
from bot.texts.text_manager import msg_text, btn_text


async def save_workout_plan(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile = await get_user_profile(callback_query.from_user.id)
    data = await state.get_data()
    completed_days = data.get("completed_days", data.get("day_index", 0) + 1)
    split_number = data.get("split")
    client_id = data.get("client_id")
    if exercises := data.get("exercises", {}):
        if completed_days >= split_number:
            await callback_query.answer(msg_text("saved", profile.language))
            client = CacheManager.get_client_by_id(client_id)
            client_profile = await ProfileService.get_profile(client_id)
            client_lang = CacheManager.get_profile_data(client_profile.tg_id, "language")
            if data.get("subscription"):
                subscription_data = CacheManager.get_subscription(client_id).to_dict()
                subscription_data.update(client_profile=client_id, exercises=exercises)
                CacheManager.update_subscription_data(client_id, {"exercises": exercises, "client_profile": client_id})
                await WorkoutService.update_subscription(subscription_data.get("id"), subscription_data)
                CacheManager.reset_program_payment_status(client_id, "subscription")
                await send_message(
                    recipient=client,
                    text=msg_text("new_program", client_lang),
                    state=state,
                    reply_markup=subscription_view_kb(client_lang),
                    include_incoming_message=False,
                )
            else:
                program_text = await format_program(exercises, 0)
                current_program = CacheManager.get_program(client_id)
                if program_data := await WorkoutService.save_program(
                    client_id, exercises, split_number, current_program.wishes
                ):
                    program_data.update(workout_type=current_program.workout_type, split_number=split_number)
                    CacheManager.set_program(client_id, program_data)
                    CacheManager.reset_program_payment_status(client_id, "program")

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

            CacheManager.set_client_data(client_id, {"status": "default"})
            await show_main_menu(callback_query.message, profile, state)
        else:
            await callback_query.answer(msg_text("complete_all_days", profile.language), show_alert=True)
    else:
        await callback_query.answer(msg_text("no_exercises_to_save", profile.language))


async def reset_workout_plan(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile = await get_user_profile(callback_query.from_user.id)
    data = await state.get_data()
    client_id = data.get("client_id")
    await callback_query.answer(btn_text("done", profile.language))
    if data.get("subscription"):
        subscription_data = CacheManager.get_subscription(client_id).to_dict()
        subscription_data.update(client_profile=client_id, exercises={})
        await WorkoutService.update_subscription(subscription_data.get("id"), subscription_data)
        CacheManager.update_subscription_data(client_id, {"exercises": None, "client_profile": client_id})
        CacheManager.set_client_data(client_id, {"status": "waiting_for_subscription"})
        CacheManager.set_payment_status(client_id, True, "subscription")
    else:
        program = CacheManager.get_program(client_id)
        await WorkoutService.update_program(program.id, dict(exercises_by_day={}))
        CacheManager.update_program_data(client_id, dict(exercises_by_day={}))
        CacheManager.set_client_data(client_id, {"status": "waiting_for_program"})
        CacheManager.set_payment_status(client_id, True, "program")
    await state.clear()
    await callback_query.message.answer(msg_text("enter_daily_program", profile.language).format(day=1))
    await state.update_data(client_id=client_id, exercises=[], day_index=0)
    await state.set_state(States.program_manage)
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


async def next_day_workout_plan(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile = await get_user_profile(callback_query.from_user.id)
    data = await state.get_data()
    completed_days = data.get("day_index", 0)
    split_number = data.get("split")
    if data.get("exercises"):
        if completed_days < split_number:
            await callback_query.answer(btn_text("forward", profile.language))
            await delete_messages(state)
            completed_days += 1
            if data.get("subscription"):
                days = data.get("days", [])
                if completed_days < len(days):
                    week_day = get_translated_week_day(profile.language, days[completed_days]).lower()
                else:
                    await callback_query.answer(msg_text("out_of_range", profile.language))
                    return

            else:
                week_day = completed_days + 1

            exercise_msg = await callback_query.message.answer(msg_text("enter_exercise", profile.language))
            await callback_query.message.answer(
                msg_text("enter_daily_program", profile.language).format(day=week_day),
                reply_markup=program_manage_kb(profile.language, split_number),
            )
            await state.update_data(
                day_index=completed_days,
                chat_id=callback_query.message.chat.id,
                message_ids=[exercise_msg.message_id],
            )
        else:
            await callback_query.answer(msg_text("out_of_range", profile.language))
            return
    else:
        await callback_query.answer(msg_text("no_exercises_to_save", profile.language))


async def manage_program(callback_query: CallbackQuery, profile: Profile, client_id: str, state: FSMContext) -> None:
    program_paid = CacheManager.check_payment_status(int(client_id), "program")
    workout_data = CacheManager.get_program(int(client_id))

    if not program_paid and not workout_data:
        await callback_query.answer(msg_text("payment_required", profile.language), show_alert=True)
        await state.set_state(States.show_clients)
        return

    if workout_data and workout_data.exercises_by_day:
        program = await format_program(workout_data.exercises_by_day, 0)
        program_msg = await callback_query.message.answer(
            msg_text("program_page", profile.language).format(program=program, day=1),
            reply_markup=program_edit_kb(profile.language),
            disable_web_page_preview=True,
        )
        await state.update_data(
            chat_id=callback_query.message.chat.id,
            message_ids=[program_msg.message_id],
            exercises=workout_data.exercises_by_day,
            client_id=client_id,
            day_index=0,
        )
        await state.set_state(States.program_edit)
        await callback_query.message.delete()
        return

    else:
        no_program_msg = await callback_query.message.answer(msg_text("no_program", profile.language))

    workouts_number_msg = await callback_query.message.answer(msg_text("workouts_number", profile.language))
    await state.update_data(
        chat_id=callback_query.message.chat.id,
        message_ids=[no_program_msg.message_id, workouts_number_msg.message_id],
        client_id=client_id,
    )
    await state.set_state(States.workouts_number)
    await callback_query.message.delete()


def cache_program_data(data: dict, profile_id: int) -> None:
    program_data = {
        "id": 1,
        "workout_type": data.get("workout_type"),
        "exercises_by_day": {},
        "created_at": datetime.now().timestamp(),
        "profile": profile_id,
        "split_number": 1,
        "wishes": data.get("wishes"),
    }
    CacheManager.set_program(profile_id, program_data)


async def cancel_subscription(next_payment_date: datetime, profile_id: int, subscription_id: int) -> None:
    now = datetime.now()
    delay = (next_payment_date - now).total_seconds()

    if delay > 0:
        await asyncio.sleep(delay)

    await WorkoutService.update_subscription(subscription_id, dict(client_profile=profile_id, enabled=False))
    CacheManager.update_subscription_data(profile_id, dict(enabled=False))
    CacheManager.reset_program_payment_status(profile_id, "subscription")
