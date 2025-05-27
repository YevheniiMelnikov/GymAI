from typing import cast

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from bot.functions.menus import show_subscription_page
from bot.functions import profiles
from bot.functions.text_utils import format_program, get_translated_week_day
from bot.functions.utils import delete_messages, generate_order_id, answer_msg, del_msg
from bot.keyboards import payment_kb, program_edit_kb, program_manage_kb
from bot.states import States
from bot.texts.exercises import exercise_dict
from bot.texts.text_manager import msg_text
from core.cache import Cache
from core.models import Exercise, Profile, Subscription, DayExercises
from core.services import APIService
from core.services.outer.gstorage_service import gif_manager


async def save_exercise(state: FSMContext, exercise: Exercise, input_data: Message | CallbackQuery) -> None:
    data = await state.get_data()
    await delete_messages(state)

    if not input_data.from_user:
        return

    profile = await profiles.get_user_profile(input_data.from_user.id)
    if not profile:
        return
    language = cast(str, profile.language or "ua")

    client_id = cast(int | None, data.get("client_id"))
    if not client_id:
        return

    day_index = cast(int, data.get("day_index", 0))
    exercises: list[DayExercises] = data.get("exercises", [])

    day_str = str(day_index)
    day_entry = next((d for d in exercises if d.day == day_str), None)

    if not day_entry:
        day_entry = DayExercises(day=day_str, exercises=[exercise])
        exercises.append(day_entry)
    elif not any(ex.name == exercise.name for ex in day_entry.exercises):
        day_entry.exercises.append(exercise)

    if data.get("subscription"):
        days: list[str] = cast(list[str], data.get("days"))
        current_day = days[day_index]
        day_label = get_translated_week_day(language, current_day).lower()
        split_number = len(days)
    else:
        day_label = day_index + 1
        split_number = cast(int | None, data.get("split"))
        if split_number is None:
            program = await Cache.workout.get_program(client_id)
            split_number = program.split_number if program else 1

    program = await format_program(exercises, day_index)

    msg: Message | None = None
    if isinstance(input_data, CallbackQuery) and isinstance(input_data.message, Message):
        msg = input_data.message
    elif isinstance(input_data, Message):
        msg = input_data

    if not msg:
        return

    exercise_msg = await answer_msg(msg, msg_text("enter_exercise", language))
    program_msg = await answer_msg(
        msg,
        msg_text("program_page", language).format(program=program, day=day_label),
        reply_markup=program_manage_kb(language, split_number),
        disable_web_page_preview=True,
    )

    message_ids = []
    if exercise_msg:
        message_ids.append(exercise_msg.message_id)
    if program_msg:
        message_ids.append(program_msg.message_id)

    await state.update_data(
        chat_id=msg.chat.id,
        message_ids=message_ids,
        exercises=exercises,
        day_index=day_index,
        split=split_number,
    )
    await state.set_state(States.program_manage)


async def find_exercise_gif(exercise: str) -> str | None:
    try:
        exercise_lc = exercise.lower()
        for filename, synonyms in exercise_dict.items():
            if exercise_lc in (syn.lower() for syn in synonyms):
                cached = await Cache.workout.get_exercise_gif(exercise_lc)
                if cached:
                    return f"https://storage.googleapis.com/{gif_manager.bucket_name}/{cached}"

                blobs = list(gif_manager.bucket.list_blobs(prefix=filename))
                if blobs:
                    blob = blobs[0]
                    if blob.exists():
                        file_url = f"https://storage.googleapis.com/{gif_manager.bucket_name}/{blob.name}"
                        for syn in synonyms:
                            await Cache.workout.cache_gif_filename(syn.lower(), blob.name)
                        return file_url
    except Exception as e:
        logger.error(f"Failed to find gif for exercise {exercise}: {e}")

    logger.debug(f"No matching file found for exercise: {exercise}")
    return None


async def update_exercise_data(message: Message, state: FSMContext, lang: str, updated_option: dict) -> None:
    data = await state.get_data()
    exercises: list[DayExercises] = data.get("exercises", [])
    day_index = str(data.get("selected_day_index", data.get("day_index", 0)))
    exercise_index = data.get("selected_ex_index", 0)

    day_entry = next((d for d in exercises if d.day == day_index), None)
    if not day_entry:
        return

    selected_ex = day_entry.exercises[exercise_index]
    for k, v in updated_option.items():
        setattr(selected_ex, k, v)

    program = await format_program(exercises, int(day_index))
    await state.update_data(exercises=exercises)
    await state.set_state(States.program_edit)

    await answer_msg(
        message,
        msg_text("program_page", lang).format(program=program, day=int(day_index) + 1),
        disable_web_page_preview=True,
    )
    await answer_msg(
        message,
        msg_text("continue_editing", lang),
        reply_markup=program_edit_kb(lang),
    )
    await del_msg(cast(Message | CallbackQuery | None, message))


async def edit_subscription_exercises(callback_query: CallbackQuery, state: FSMContext) -> None:
    if not callback_query.from_user:
        return

    profile = await profiles.get_user_profile(callback_query.from_user.id)
    if not profile:
        return
    language = cast(str, profile.language or "ua")

    if not callback_query.data:
        return

    parts = cast(str, callback_query.data).split("_")
    client_id = int(parts[1])
    day = parts[2]

    subscription = await Cache.workout.get_subscription(client_id)
    if not subscription:
        return

    week_day = get_translated_week_day(language, day).lower()
    day_index = subscription.workout_days.index(day)
    program_text = await format_program(subscription.exercises, day_index)

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
    if callback_query.message and isinstance(callback_query.message, Message):
        await answer_msg(
            callback_query.message,
            msg_text("program_page", language).format(program=program_text, day=week_day),
            disable_web_page_preview=True,
            reply_markup=program_edit_kb(language),
        )
        await del_msg(callback_query.message)


async def edit_subscription_days(
    callback_query: CallbackQuery,
    days: list[str],
    profile: Profile,
    state: FSMContext,
    subscription: Subscription,
) -> None:
    subscription_data = subscription.model_dump()
    exercises_data = subscription_data.get("exercises", [])
    exercises = [DayExercises.model_validate(e) for e in exercises_data]
    updated_exercises = {days[i]: [e.model_dump() for e in day.exercises] for i, day in enumerate(exercises)}

    payload = {"workout_days": days, "exercises": updated_exercises, "client_profile": profile.id}
    subscription_data.update(payload)

    await Cache.workout.update_subscription(profile.id, payload)
    await APIService.workout.update_subscription(cast(int, subscription_data["id"]), subscription_data)

    await state.set_state(States.show_subscription)
    await show_subscription_page(callback_query, state, subscription)
    if isinstance(callback_query, CallbackQuery) and isinstance(callback_query.message, Message):
        await del_msg(callback_query.message)


async def process_new_subscription(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    language = cast(str, profile.language or "ua")

    await callback_query.answer(msg_text("checkbox_reminding", language), show_alert=True)

    order_id = generate_order_id()
    client = await Cache.client.get_client(profile.id)
    if not client or not client.assigned_to:
        return
    coach = await Cache.coach.get_coach(client.assigned_to.pop())
    if not coach:
        return

    await state.update_data(order_id=order_id, amount=coach.subscription_price)

    payment_link = await APIService.payment.get_payment_link(
        action="subscribe",
        amount=str(coach.subscription_price),
        order_id=order_id,
        payment_type="subscription",
        profile_id=profile.id,
    )

    if not isinstance(callback_query.message, Message):
        return

    message = callback_query.message
    if payment_link:
        await state.set_state(States.handle_payment)
        await answer_msg(
            message,
            msg_text("follow_link", language),
            reply_markup=payment_kb(language, payment_link, "subscription"),
        )
    else:
        await answer_msg(message, msg_text("unexpected_error", language))

    await del_msg(message)
