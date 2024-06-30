import loguru
from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import gift
from bot.states import States
from common.functions import *
from common.models import Coach, Profile
from common.user_service import user_service
from texts.text_manager import MessageText, translate

main_router = Router()
logger = loguru.logger


@main_router.callback_query(States.main_menu)
async def main_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    match callback_query.data:
        case "feedback":
            await callback_query.message.answer(text=translate(MessageText.feedback, lang=profile.language))
            await state.set_state(States.feedback)
            await callback_query.message.delete()

        case "my_profile":
            await handle_my_profile(callback_query, profile, state)

        case "my_clients":
            await handle_my_clients(callback_query, profile, state)

        case "my_program":
            await handle_my_program(callback_query, profile, state)


@main_router.callback_query(States.profile)
async def profile_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    data = await state.get_data()
    profile = Profile.from_dict(data["profile"])
    if callback_query.data == "edit_profile":
        await show_profile_editing_menu(callback_query.message, profile, state)
    elif callback_query.data == "back":
        await show_main_menu(callback_query.message, profile, state)


@main_router.message(States.password_reset)
async def process_password_reset(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    index = next((i for i, username in enumerate(data["usernames"]) if username == message.text), None)
    if index is not None and data["emails"][index]:
        email = data["emails"][index]
        profile = Profile.from_dict(data["profiles"][index])
        token = user_service.storage.get_profile_info_by_key(message.from_user.id, profile.id, "auth_token")
        if not token:
            raise ValueError(f"Authentication token not found for user {profile.id}")
        if await user_service.reset_password(email, token):
            await message.answer(text=translate(MessageText.password_reset_sent, profile.language).format(email=email))
            await state.clear()
            await user_service.log_out(message.from_user.id)
            await message.answer(text=translate(MessageText.username, profile.language))
            await state.set_state(States.username)
        else:
            await message.answer(text=translate(MessageText.unexpected_error, profile.language))
    else:
        await message.answer(text=translate(MessageText.no_profiles_found, data.get("lang")))
        await message.answer(text=translate(MessageText.help, data.get("lang")))
        await state.clear()
    await message.delete()


@main_router.message(States.feedback)
async def handle_feedback(message: Message, state: FSMContext) -> None:
    profile = user_service.storage.get_current_profile(message.from_user.id)
    auth_token = user_service.storage.get_profile_info_by_key(message.from_user.id, profile.id, "auth_token")
    if user_data := await user_service.get_user_data(auth_token):
        if await user_service.send_feedback(user_data.get("email"), user_data.get("username"), message.text):
            logger.info(f"User {profile.id} sent feedback")
            await message.answer(text=translate(MessageText.feedback_sent, lang=profile.language))
        else:
            await message.answer(text=translate(MessageText.unexpected_error, lang=profile.language))
        await show_main_menu(message, profile, state)
    else:
        await message.answer(text=translate(MessageText.unexpected_error, lang=profile.language))
        await show_main_menu(message, profile, state)


@main_router.callback_query(States.choose_coach)
async def choose_coach_menu(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    if callback_query.data == "back":
        await state.set_state(States.main_menu)
        await show_main_menu(callback_query.message, profile, state)
        return

    else:
        coaches = user_service.storage.get_coaches()
        if not coaches:
            await callback_query.message.answer(translate(MessageText.no_coaches, lang=profile.language))
            await state.set_state(States.main_menu)
            await show_main_menu(callback_query.message, profile, state)
            return

        await state.set_state(States.coach_selection)
        await state.update_data(coaches=[Coach.to_dict(coach) for coach in coaches])
        await show_coaches(callback_query.message, coaches)


@main_router.callback_query(States.coach_selection)
async def coach_paginator(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)

    if callback_query.data == "quit":
        await state.set_state(States.main_menu)
        await show_main_menu(callback_query.message, profile, state)
        return

    action, index = callback_query.data.split("_")
    index = int(index)
    data = await state.get_data()
    coaches = [Coach.from_dict(data) for data in data["coaches"]]
    if not coaches:
        await callback_query.answer(translate(MessageText.no_coaches, profile.language))
        return

    if index < 0 or index >= len(coaches) and action != "selected":
        await callback_query.answer(translate(MessageText.out_of_range, profile.language))
        return

    if action == "selected":
        await callback_query.answer(translate(MessageText.saved, profile.language))
        coach_id = callback_query.data.split("_")[1]
        coach = user_service.storage.get_coach_by_id(coach_id)
        client = user_service.storage.get_client_by_id(profile.id)
        await assign_coach(coach, client)
        await state.update_data(coach=coach.to_dict(), client=client.to_dict())
        await state.set_state(States.gift)
        await callback_query.message.answer(
            translate(MessageText.gift, profile.language), reply_markup=gift(profile.language)
        )
        await callback_query.message.delete()
    else:
        await show_coaches(callback_query.message, coaches, current_index=index)


@main_router.callback_query(States.show_clients)
async def client_paginator(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)

    if callback_query.data == "back":
        await callback_query.answer()
        await show_main_menu(callback_query.message, profile, state)
        await state.set_state(States.main_menu)
        return

    action, client_id = callback_query.data.split("_")
    if action == "contact":
        await handle_contact_action(callback_query, profile, client_id, state)
        return

    if action == "program":
        await handle_program_action(callback_query, profile, client_id, state)
        return

    if action == "subscription":
        await handle_subscription_action(callback_query, profile, client_id, state)
        return

    try:
        index = int(client_id)
    except ValueError:
        await callback_query.answer(translate(MessageText.out_of_range, profile.language))
        return

    await handle_client_pagination(callback_query, profile, index, state)


@main_router.callback_query(States.show_subscription)
async def show_subscription(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    if callback_query.data == "back":
        await state.set_state(States.select_service)
        await callback_query.message.answer(
            text=translate(MessageText.select_service, lang=profile.language),
            reply_markup=select_service(profile.language),
        )

    elif callback_query.data == "edit":
        await state.update_data(edit_mode=True)
        await state.set_state(States.workout_days)
        await callback_query.message.answer(
            translate(MessageText.select_days, profile.language), reply_markup=select_days(profile.language, [])
        )

    elif callback_query.data == "contact":
        client = user_service.storage.get_client_by_id(profile.id)
        coach_id = client.assigned_to.pop()
        await state.update_data(recipient_id=coach_id, sender_name=client.name)
        await state.set_state(States.contact_coach)
        await callback_query.message.answer(translate(MessageText.enter_your_message, profile.language))

    else:
        subscription = user_service.storage.get_subscription(profile.id)
        workout_days = subscription.workout_days
        await state.update_data(exercises=subscription.exercises, days=workout_days, split=len(workout_days))
        await show_exercises(callback_query, state, profile)

    with suppress(TelegramBadRequest):
        await callback_query.message.delete()
