from loguru import logger
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.keyboards import new_message_kb, workout_results_kb
from bot.states import States
from core.cache import Cache
from core.exceptions import UserServiceError
from functions.chat import send_message
from functions.menus import show_main_menu
from functions.profiles import get_user_profile
from bot.texts.text_manager import msg_text
from core.services.profile_service import ProfileService


chat_router = Router()


@chat_router.message(States.contact_client, F.text | F.photo | F.video)
async def contact_client(message: Message, state: FSMContext):
    data = await state.get_data()
    profile = await get_user_profile(message.from_user.id)

    try:
        client = Cache.client.get_client(data.get("recipient_id"))
        if client.status == "waiting_for_text":
            Cache.client.set_client_data(client.id, {"status": "default"})
        client_profile = await ProfileService.get_profile(client.id)
        coach_name = Cache.coach.get_coach(profile.id).name
    except Exception as e:
        logger.error(f"Can't get data: {e}")
        await message.answer(msg_text("unexpected_error", profile.language))
        await show_main_menu(message, profile, state)
        return

    await state.update_data(sender_name=coach_name)
    await state.update_data(recipient_language=client_profile.language)

    if message.photo:
        photo = message.photo[-1]
        caption = message.caption if message.caption else ""
        await send_message(
            client, caption, state, reply_markup=new_message_kb(client_profile.language, profile.id), photo=photo
        )
    elif message.video:
        video = message.video
        caption = message.caption if message.caption else ""
        await send_message(
            client, caption, state, reply_markup=new_message_kb(client_profile.language, profile.id), video=video
        )
    else:
        await send_message(
            client, message.text, state, reply_markup=new_message_kb(client_profile.language, profile.id)
        )

    await message.answer(msg_text("message_sent", profile.language))
    logger.debug(f"Coach {profile.id} sent message to client {client.id}")
    await show_main_menu(message, profile, state)


@chat_router.message(States.contact_coach, F.text | F.photo | F.video)
async def contact_coach(message: Message, state: FSMContext):
    data = await state.get_data()
    profile = await get_user_profile(message.from_user.id)

    try:
        coach = Cache.coach.get_coach(data.get("recipient_id"))
        if not coach:
            raise UserServiceError("Coach not found in cache", 404, f"recipient_id: {data.get('recipient_id')}")

        coach_profile = await ProfileService.get_profile(coach.id)
        if not coach_profile:
            raise UserServiceError("Coach profile not found", 404, f"coach_id: {coach.id}")

        client_name = Cache.client.get_client(profile.id).name
        if not client_name:
            raise UserServiceError("Client name not found", 404, f"profile_id: {profile.id}")

    except UserServiceError as error:
        logger.error(f"UserServiceError - {error}")
        await message.answer(msg_text("unexpected_error", profile.language))
        await show_main_menu(message, profile, state)
        return
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        await message.answer(msg_text("unexpected_error", profile.language))
        await show_main_menu(message, profile, state)
        return

    await state.update_data(sender_name=client_name)
    await state.update_data(recipient_language=coach_profile.language)

    if message.photo:
        photo = message.photo[-1]
        caption = message.caption if message.caption else ""
        await send_message(
            coach, caption, state, reply_markup=new_message_kb(coach_profile.language, profile.id), photo=photo
        )
    elif message.video:
        video = message.video
        caption = message.caption if message.caption else ""
        await send_message(
            coach, caption, state, reply_markup=new_message_kb(coach_profile.language, profile.id), video=video
        )
    else:
        await send_message(coach, message.text, state, reply_markup=new_message_kb(coach_profile.language, profile.id))

    await message.answer(msg_text("message_sent", profile.language))
    logger.debug(f"Client {profile.id} sent message to coach {coach.id}")
    await show_main_menu(message, profile, state)


@chat_router.callback_query(F.data.startswith("yes_"))
@chat_router.callback_query(F.data.startswith("no_"))
async def have_you_trained(callback_query: CallbackQuery, state: FSMContext):
    profile = await get_user_profile(callback_query.from_user.id)
    subscription = Cache.workout.get_subscription(profile.id)

    try:
        _, weekday = callback_query.data.split("_", 1)
    except ValueError:
        await callback_query.answer("❓")
        return

    workout_days = subscription.workout_days or []
    try:
        day_index = workout_days.index(weekday)
    except ValueError:
        day_index = -1

    if callback_query.data.startswith("yes"):
        exercises = subscription.exercises.get(str(day_index)) or subscription.exercises.get(weekday)

        await state.update_data(
            exercises=exercises,
            day=weekday,
            day_index=day_index,
        )
        await callback_query.answer("🔥")
        await callback_query.message.answer(
            msg_text("workout_results", profile.language),
            reply_markup=workout_results_kb(profile.language),
        )
        await callback_query.message.delete()
        await state.set_state(States.workout_survey)
    else:
        await callback_query.answer("😢")
        await callback_query.message.delete()
        logger.debug(f"User {profile.id} reported no training on {weekday}")
