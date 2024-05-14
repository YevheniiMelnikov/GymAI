import loguru
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import choose_coach, profile_menu_keyboard
from bot.states import States
from common.file_manager import file_manager
from common.functions import (
    assign_coach,
    show_coaches,
    show_main_menu,
    show_profile_editing_menu,
    show_program,
    show_subscription,
)
from common.models import Coach, Profile
from common.user_service import user_service
from common.utils import get_profile_attributes
from texts.text_manager import MessageText, translate

main_router = Router()
logger = loguru.logger


@main_router.callback_query(States.main_menu)
async def main_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = user_service.storage.get_current_profile(callback_query.from_user.id) or Profile.from_dict(
        data["profile"]
    )
    match callback_query.data:
        case "feedback":
            await callback_query.message.answer(text=translate(MessageText.feedback, lang=profile.language))
            await state.set_state(States.feedback)
        case "my_profile":
            user = (
                user_service.storage.get_client_by_id(profile.id)
                if profile.status == "client"
                else user_service.storage.get_coach_by_id(profile.id)
            )
            format_attributes = get_profile_attributes(role=profile.status, user=user, lang_code=profile.language)
            text = translate(
                MessageText.client_profile if profile.status == "client" else MessageText.coach_profile,
                lang=profile.language,
            ).format(**format_attributes)
            if profile.status == "coach" and getattr(user, "profile_photo", None):
                photo = file_manager.generate_signed_url(user.profile_photo)
                await callback_query.message.answer_photo(
                    photo, text, reply_markup=profile_menu_keyboard(profile.language)
                )
            else:
                await callback_query.message.answer(text, reply_markup=profile_menu_keyboard(profile.language))
            await state.set_state(States.profile)
        case "my_clients":  # TODO: IMPLEMENT
            await callback_query.message.answer(text="Ваши клиенты: ")
        case "my_program":  # TODO: IMPLEMENT
            if program := user_service.storage.get_program(profile.id):
                await show_program(callback_query.message, program)
            else:
                await callback_query.message.answer(
                    text=translate(MessageText.no_program, lang=profile.language),
                    reply_markup=choose_coach(profile.language),
                )
                await state.set_state(States.choose_coach)
        case "my_subscription":  # TODO: IMPLEMENT
            if subscription := user_service.storage.get_subscription(profile.id):
                await show_subscription(callback_query.message, subscription)

    await callback_query.message.delete()


@main_router.callback_query(States.profile)
async def profile_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
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
            await message.answer(text=translate(MessageText.username, profile.language))
            await state.set_state(States.username)
        else:
            await message.answer(text=translate(MessageText.unexpected_error, profile.language))
    else:
        await message.answer(text=translate(MessageText.no_profiles_found, data["lang"]))
        await message.answer(text=translate(MessageText.help, data["lang"]))
    await message.delete()


@main_router.message(States.feedback)
async def handle_feedback(message: Message, state: FSMContext) -> None:
    profile = user_service.storage.get_current_profile(message.from_user.id)
    auth_token = user_service.storage.get_profile_info_by_key(message.from_user.id, profile.id, "auth_token")
    if user_data := await user_service.get_user_data(auth_token):
        if await user_service.send_feedback(user_data.get("email"), user_data.get("username"), message.text):
            logger.info(f"{user_data.get('username')} sent feedback")
            await message.answer(text=translate(MessageText.feedback_sent, lang=profile.language))
        else:
            await message.answer(text=translate(MessageText.unexpected_error, lang=profile.language))
        await show_main_menu(message, profile, state)
    else:
        await message.answer(text=translate(MessageText.unexpected_error, lang=profile.language))
        await show_main_menu(message, profile, state)


@main_router.callback_query(States.choose_coach)
async def choose_coach_menu(callback_query: CallbackQuery, state: FSMContext):
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
        await callback_query.message.delete()


@main_router.callback_query(States.coach_selection)
async def coach_paginator(callback_query: CallbackQuery, state: FSMContext):
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
        await callback_query.message.answer(translate(MessageText.coach_selected).format(name=coach.name))
        await state.set_state(States.main_menu)
        await show_main_menu(callback_query.message, profile, state)
    else:
        await show_coaches(callback_query.message, coaches, current_index=index)
