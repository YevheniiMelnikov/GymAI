import loguru
from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.keyboards import (
    choose_coach,
    profile_menu_keyboard,
    program_manage_menu,
    select_program_type,
)
from bot.states import States
from common.file_manager import avatar_manager
from common.functions import (
    assign_coach,
    format_program,
    show_clients,
    show_coaches,
    show_main_menu,
    show_profile_editing_menu,
)
from common.models import Client, Coach, Profile
from common.user_service import user_service
from common.utils import get_profile_attributes
from texts.text_manager import ButtonText, MessageText, translate

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
                photo = avatar_manager.generate_signed_url(user.profile_photo)
                try:
                    await callback_query.message.answer_photo(
                        photo, text, reply_markup=profile_menu_keyboard(profile.language)
                    )
                except TelegramBadRequest:
                    logger.error(f"Profile image of profile_id {profile.id} not found")
                    await callback_query.message.answer(text, reply_markup=profile_menu_keyboard(profile.language))
            else:
                await callback_query.message.answer(text, reply_markup=profile_menu_keyboard(profile.language))
            await state.set_state(States.profile)

        case "my_clients":
            coach = user_service.storage.get_coach_by_id(profile.id)
            assigned_ids = coach.assigned_to if coach.assigned_to != [] else None
            if assigned_ids:
                clients = [user_service.storage.get_client_by_id(client) for client in assigned_ids]
                await show_clients(callback_query.message, clients, state)
            else:
                if not coach.verified:
                    await callback_query.message.answer(translate(MessageText.coach_info_message, profile.language))
                await callback_query.message.answer(translate(MessageText.no_clients, profile.language))
                await state.set_state(States.main_menu)
                await show_main_menu(callback_query.message, profile, state)
            return

        case "my_program":
            client = user_service.storage.get_client_by_id(profile.id)
            assigned = client.assigned_to if client.assigned_to != [] else None
            if not assigned:
                await callback_query.message.answer(
                    text=translate(MessageText.no_program, lang=profile.language),
                    reply_markup=choose_coach(profile.language),
                )
                await state.set_state(States.choose_coach)
            else:
                exercises = user_service.storage.get_program(str(profile.id))
                if exercises and exercises.get("exercises"):
                    program = await format_program(exercises.get("exercises"))
                    await callback_query.message.answer(
                        text=translate(MessageText.current_program, lang=profile.language).format(program=program),
                        reply_markup=InlineKeyboardMarkup(
                            inline_keyboard=[
                                [
                                    InlineKeyboardButton(
                                        text=translate(ButtonText.back, profile.language), callback_data="back"
                                    )
                                ]
                            ]
                        ),
                    )
                    await state.set_state(States.program)
                else:
                    await state.set_state(States.select_program_type)
                    await callback_query.message.answer(
                        text=translate(MessageText.no_program, lang=profile.language),
                        reply_markup=select_program_type(profile.language),
                    )

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
        await message.answer(text=translate(MessageText.no_profiles_found, data.get("lang")))
        await message.answer(text=translate(MessageText.help, data.get("lang")))
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
        await state.set_state(States.main_menu)  # TODO: GIVE FREE CONSULTATION AS GIFT
        await show_main_menu(callback_query.message, profile, state)
    else:
        await show_coaches(callback_query.message, coaches, current_index=index)


@main_router.callback_query(States.show_clients)
async def client_paginator(callback_query: CallbackQuery, state: FSMContext):
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)

    if callback_query.data == "quit":
        await state.set_state(States.main_menu)
        await show_main_menu(callback_query.message, profile, state)
        return

    action, client_id = callback_query.data.split("_")
    if action == "contact":
        await callback_query.message.answer(translate(MessageText.enter_your_message, profile.language))
        await callback_query.message.delete()
        coach = user_service.storage.get_coach_by_id(profile.id)
        await state.clear()
        await state.update_data(recipient_id=client_id, sender_name=coach.name)
        await state.set_state(States.contact_client)
        return

    if action == "program":
        await callback_query.message.answer(translate(MessageText.program_guide))
        exercises_data = user_service.storage.get_program(str(client_id))
        exercises = exercises_data.get("exercises")
        if exercises:
            exercises_tuples = [(exercise,) if isinstance(exercise, str) else exercise for exercise in exercises]
            program = await format_program(exercises_tuples)
            del_msg = await callback_query.message.answer(
                text=translate(MessageText.current_program, lang=profile.language).format(program=program),
                reply_markup=program_manage_menu(profile.language), disable_web_page_preview=True,
            )
            await state.update_data(exercises=exercises_tuples)
        else:
            del_msg = await callback_query.message.answer(
                text=translate(MessageText.no_program, lang=profile.language),
                reply_markup=program_manage_menu(profile.language),
            )
        await state.update_data(client_id=client_id, del_msg=del_msg.message_id)
        await callback_query.message.delete()
        await state.set_state(States.program_manage)
        return

    index = int(callback_query.data.split("_")[1])
    data = await state.get_data()
    clients = [Client.from_dict(data) for data in data["clients"]]

    if not clients:
        await callback_query.answer(translate(MessageText.no_clients, profile.language))
        return

    if index < 0 or index >= len(clients):
        await callback_query.answer(translate(MessageText.out_of_range, profile.language))
        return

    await show_clients(callback_query.message, clients, state, index)


@main_router.callback_query(States.program)
async def show_program(callback_query: CallbackQuery, state: FSMContext):
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    if callback_query.data == "back":
        await state.set_state(States.main_menu)
        await show_main_menu(callback_query.message, profile, state)
