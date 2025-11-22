from typing import cast

from loguru import logger
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.keyboards import workout_results_kb
from bot.states import States
from bot.utils.ask_ai import start_ask_ai_prompt
from core.cache import Cache
from core.schemas import Profile
from bot.utils.exercises import edit_subscription_exercises
from bot.utils.menus import show_main_menu, show_exercises_menu, program_menu_pagination
from bot.texts.text_manager import msg_text
from bot.utils.bot import del_msg, answer_msg

chat_router = Router()


@chat_router.callback_query(F.data.startswith("yes_") | F.data.startswith("no_"))
async def have_you_trained(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    assert profile is not None
    profile_record = await Cache.profile.get_record(profile.id)
    subscription = await Cache.workout.get_latest_subscription(profile_record.id)
    assert subscription is not None

    data_str = cast(str, callback_query.data)
    try:
        _, weekday = data_str.split("_", 1)
    except ValueError:
        await callback_query.answer("❓")
        return

    workout_days = subscription.workout_days or []
    day_index = workout_days.index(weekday) if weekday in workout_days else -1

    if data_str.startswith("yes"):
        exercises = next(
            (
                day.exercises
                for day in subscription.exercises
                if day.day == weekday or subscription.exercises.index(day) == day_index
            ),
            [],
        )

        await state.update_data(exercises=exercises, day=weekday, day_index=day_index)
        await callback_query.answer("🔥")
        if callback_query.message and isinstance(callback_query.message, Message):
            await answer_msg(
                callback_query.message,
                msg_text("workout_results", profile.language),
                reply_markup=workout_results_kb(profile.language),
            )
            await del_msg(callback_query.message)
        await state.set_state(States.workout_survey)
    else:
        await callback_query.answer("😢")
        if callback_query.message and isinstance(callback_query.message, Message):
            await del_msg(callback_query.message)
        logger.debug(f"User {profile.id} reported no training on {weekday}")


@chat_router.callback_query(F.data.in_({"quit", "later"}))
async def close_notification(callback_query: CallbackQuery, state: FSMContext) -> None:
    if callback_query.message and isinstance(callback_query.message, Message):
        await del_msg(callback_query.message)
    data = await state.get_data()
    profile_dict = data.get("profile")
    if profile_dict:
        profile = Profile.model_validate(profile_dict)
        if callback_query.message and isinstance(callback_query.message, Message):
            await show_main_menu(cast(Message, callback_query.message), profile, state)


@chat_router.callback_query(F.data == "subscription_view")
async def subscription_view(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    assert profile is not None
    profile_record = await Cache.profile.get_record(profile.id)
    subscription = await Cache.workout.get_latest_subscription(profile_record.id)
    assert subscription is not None

    await state.update_data(
        exercises=subscription.exercises,
        split=len(subscription.workout_days),
        days=subscription.workout_days,
        subscription=True,
    )
    await show_exercises_menu(callback_query, state, profile)


@chat_router.callback_query(F.data.startswith("answer"))
async def answer_message(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    assert profile is not None

    data_str = cast(str, callback_query.data)
    try:
        int(data_str.split("_", 1)[1])
    except (IndexError, ValueError):
        await callback_query.answer("Invalid recipient id")
        return


@chat_router.callback_query(F.data.in_({"previous", "next"}))
async def navigate_days(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    assert profile is not None
    profile_record = await Cache.profile.get_record(profile.id)
    program = await Cache.workout.get_latest_program(profile_record.id)

    if data.get("subscription"):
        subscription = await Cache.workout.get_latest_subscription(profile_record.id)
        assert subscription is not None
        split_number = len(subscription.workout_days)
        exercises = subscription.exercises
    else:
        assert program is not None
        split_number = program.split_number
        exercises = program.exercises_by_day

    await state.update_data(exercises=exercises, split=split_number, client=True)
    await program_menu_pagination(state, callback_query)


@chat_router.callback_query(F.data.startswith("edit_"))
async def edit_subscription(callback_query: CallbackQuery, state: FSMContext) -> None:
    await edit_subscription_exercises(callback_query, state)


@chat_router.callback_query(F.data.startswith("ask_ai_again"))
async def ask_ai_repeat(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        await callback_query.answer()
        return
    profile = Profile.model_validate(profile_data)
    handled = await start_ask_ai_prompt(
        callback_query,
        profile,
        state,
        delete_origin=False,
        show_balance_menu_on_insufficient=False,
    )
    if handled:
        await callback_query.answer()
