import os
from contextlib import suppress

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import payment_kb, program_edit_kb, program_manage_kb
from bot.states import States
from loguru import logger

from core.cache import Cache
from core.services.gstorage_service import gif_manager
from core.services.workout_service import WorkoutService
from functions.menus import show_subscription_page
from functions import profiles
from functions.text_utils import format_program, get_translated_week_day
from functions.utils import delete_messages, generate_order_id
from core.models import Exercise, Profile, Subscription
from core.services.payment_service import PaymentService
from bot.texts.exercises import exercise_dict
from bot.texts.text_manager import msg_text

bot = Bot(os.environ.get("BOT_TOKEN"))


async def save_exercise(state: FSMContext, exercise: Exercise, input_data: Message | CallbackQuery) -> None:
    data = await state.get_data()
    await delete_messages(state)
    profile = await profiles.get_user_profile(input_data.from_user.id)
    day_index = data.get("day_index", 0)
    client_id = data.get("client_id")
    exercises = data.get("exercises", {})

    if data.get("subscription"):
        days = data.get("days")
        current_day = days[day_index]
        day = get_translated_week_day(profile.language, current_day).lower()

        if str(day_index) not in exercises:
            exercises[str(day_index)] = [exercise.to_dict()]
        else:
            if not any(ex["name"] == exercise.name for ex in exercises[str(day_index)]):
                exercises[str(day_index)].append(exercise.to_dict())
        subscription_data = Cache.workout.get_subscription(client_id)
        split_number = len(subscription_data.workout_days)
        program = await format_program({days[day_index]: exercises[str(day_index)]}, days[day_index])
    else:
        day = day_index + 1
        if str(day_index) not in exercises:
            exercises[str(day_index)] = [exercise.to_dict()]
        else:
            if not any(ex["name"] == exercise.name for ex in exercises[str(day_index)]):
                exercises[str(day_index)].append(exercise.to_dict())
        program_data = Cache.workout.get_program(client_id)
        split_number = data.get("split", program_data.split_number)
        program = await format_program({str(day_index): exercises[str(day_index)]}, day_index)

    exercise_msg = await (input_data.answer if isinstance(input_data, Message) else input_data.message.answer)(
        msg_text("enter_exercise", profile.language)
    )
    program_msg = await exercise_msg.answer(
        msg_text("program_page", profile.language).format(program=program, day=day),
        reply_markup=program_manage_kb(profile.language, split_number),
        disable_web_page_preview=True,
    )

    await state.update_data(
        chat_id=input_data.chat.id if isinstance(input_data, Message) else input_data.message.chat.id,
        message_ids=[exercise_msg.message_id, program_msg.message_id],
        exercises=exercises,
        day_index=day_index,
        split=split_number,
    )
    await state.set_state(States.program_manage)


async def find_exercise_gif(exercise: str) -> str | None:
    try:
        exercise = exercise.lower()
        for filename, synonyms in exercise_dict.items():
            if exercise in (syn.lower() for syn in synonyms):
                cached_filename = Cache.workout.get_exercise_gif(exercise)
                if cached_filename:
                    return f"https://storage.googleapis.com/{gif_manager.bucket_name}/{cached_filename}"

                blobs = list(gif_manager.bucket.list_blobs(prefix=filename))
                if blobs:
                    matching_blob = blobs[0]
                    if matching_blob.exists():
                        file_url = f"https://storage.googleapis.com/{gif_manager.bucket_name}/{matching_blob.name}"
                        for synonym in synonyms:
                            Cache.workout.cache_gif_filename(synonym.lower(), matching_blob.name)
                        return file_url

    except Exception as e:
        logger.error(f"Failed to find gif for exercise {exercise}: {e}")

    logger.debug(f"No matching file found for exercise: {exercise}")
    return None


async def update_exercise_data(message: Message, state: FSMContext, lang: str, updated_option: dict) -> None:
    data = await state.get_data()
    exercises = data.get("exercises", [])
    day_index = data.get("day_index", 0)
    exercise_index = data.get("exercise_index", 0)
    selected_exercise = exercises[exercise_index]
    updated_key = list(updated_option.keys())[0]
    updated_value = list(updated_option.values())[0]
    selected_exercise[updated_key] = updated_value
    exercises[exercise_index] = selected_exercise
    await state.update_data(exercises=exercises)
    await state.set_state(States.program_edit)
    program = await format_program({str(day_index): exercises}, day_index)
    await message.answer(
        msg_text("program_page", lang).format(program=program, day=day_index + 1),
        disable_web_page_preview=True,
    )
    await message.answer(msg_text("continue_editing", lang), reply_markup=program_edit_kb(lang))
    with suppress(TelegramBadRequest):
        await message.delete()


async def edit_subscription_exercises(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile = await profiles.get_user_profile(callback_query.from_user.id)
    client_id = int(callback_query.data.split("_")[1])
    day = callback_query.data.split("_")[2]
    week_day = get_translated_week_day(profile.language, day).lower()
    subscription = Cache.workout.get_subscription(client_id)
    day_index = subscription.workout_days.index(day)
    program_text = await format_program(subscription.exercises, 0)
    await state.update_data(
        exercises=subscription.exercises,
        client_id=client_id,
        day=day,
        subscription=True,
        day_index=day_index,
        days=subscription.workout_days,
        completed_days=len(subscription.workout_days),
    )
    await state.set_state(States.program_edit)
    await callback_query.message.answer(
        msg_text("program_page", profile.language).format(program=program_text, day=week_day),
        disable_web_page_preview=True,
        reply_markup=program_edit_kb(profile.language),
    )
    await callback_query.message.delete()


async def edit_subscription_days(
    callback_query: CallbackQuery, days: list[str], profile: Profile, state: FSMContext, subscription: Subscription
) -> None:
    subscription_data = subscription.to_dict()
    exercises = subscription_data.get("exercises", {})
    updated_exercises = {days[i]: exercises for i, exercises in enumerate(exercises.values())}
    payload = {"workout_days": days, "exercises": updated_exercises, "client_profile": profile.id}
    subscription_data.update(payload)
    Cache.workout.update_subscription(profile.id, payload)
    await WorkoutService.update_subscription(subscription_data.get("id"), subscription_data)
    await state.set_state(States.show_subscription)
    await show_subscription_page(callback_query, state, subscription)
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


async def process_new_subscription(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    await callback_query.answer(msg_text("checkbox_reminding", profile.language), show_alert=True)
    order_id = generate_order_id()
    client = Cache.client.get_client(profile.id)
    coach = Cache.coach.get_coach(client.assigned_to.pop())
    await state.update_data(order_id=order_id, amount=coach.subscription_price)
    if payment_link := await PaymentService.get_payment_link(
        action="subscribe",
        amount=str(coach.subscription_price),
        order_id=order_id,
        payment_type="subscription",
        profile_id=profile.id,
    ):
        await state.set_state(States.handle_payment)
        await callback_query.message.answer(
            msg_text("follow_link", profile.language),
            reply_markup=payment_kb(profile.language, payment_link, "subscription"),
        )
    else:
        await callback_query.message.answer(msg_text("unexpected_error", profile.language))
    await callback_query.message.delete()
