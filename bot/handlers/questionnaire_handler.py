from contextlib import suppress

import loguru
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.keyboards import choose_gender, select_days, workout_experience_keyboard
from bot.states import States
from common.file_manager import avatar_manager
from common.functions.chat import client_request
from common.functions.menus import show_main_menu, show_subscription_page
from common.functions.profiles import update_user_info
from common.functions.text_utils import get_state_and_message, validate_birth_date
from common.functions.utils import delete_messages
from common.models import Client, Coach
from common.user_service import user_service
from texts.text_manager import MessageText, translate

logger = loguru.logger

questionnaire_router = Router()


@questionnaire_router.callback_query(States.gender)
async def gender(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await callback_query.answer(translate(MessageText.saved, lang=data.get("lang")))
    age_msg = await callback_query.message.answer(text=translate(MessageText.birth_date, lang=data.get("lang")))
    await state.update_data(
        gender=callback_query.data, chat_id=callback_query.message.chat.id, message_ids=[age_msg.message_id]
    )
    await callback_query.message.delete()
    await state.set_state(States.birth_date)


@questionnaire_router.message(States.birth_date, F.text)
async def birth_date(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    if validate_birth_date(message.text):
        goals_msg = await message.answer(translate(MessageText.workout_goals, lang=data.get("lang")))
        await state.update_data(birth_date=message.text, chat_id=message.chat.id, message_ids=[goals_msg.message_id])
        await state.set_state(States.workout_goals)
    else:
        data = await state.get_data()
        await message.answer(message.text)
        await message.answer(translate(MessageText.invalid_content, lang=data.get("lang")))
    await message.delete()


@questionnaire_router.message(States.workout_goals, F.text)
async def workout_goals(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    await state.update_data(workout_goals=message.text)
    data = await state.get_data()
    if data.get("edit_mode"):
        await update_user_info(message, state, "client")
        return

    experience_msg = await message.answer(
        translate(MessageText.workout_experience, lang=data.get("lang")),
        reply_markup=workout_experience_keyboard(data.get("lang")),
    )
    await state.update_data(chat_id=message.chat.id, message_ids=[experience_msg.message_id])
    await state.set_state(States.workout_experience)
    await message.delete()


@questionnaire_router.callback_query(States.workout_experience)
async def workout_experience(callback_query: CallbackQuery, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    await callback_query.answer(translate(MessageText.saved, lang=data.get("lang")))
    await state.update_data(workout_experience=callback_query.data)
    if data.get("edit_mode"):
        await update_user_info(callback_query.message, state, "client")
        return

    weight_msg = await callback_query.message.answer(translate(MessageText.weight, lang=data.get("lang")))
    await state.update_data(chat_id=callback_query.message.chat.id, message_ids=[weight_msg.message_id])
    await state.set_state(States.weight)
    await callback_query.message.delete()


@questionnaire_router.message(States.weight, F.text)
async def weight(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await delete_messages(state)
    if not all(map(lambda x: x.isdigit(), message.text.split())):
        await message.answer(translate(MessageText.invalid_content, lang=data.get("lang")))
        await state.set_state(States.weight)
        return

    await state.update_data(weight=message.text)
    if data.get("edit_mode"):
        await update_user_info(message, state, "client")
        return

    health_msg = await message.answer(translate(MessageText.health_notes, lang=data.get("lang")))
    await state.update_data(chat_id=message.chat.id, message_ids=[health_msg.message_id])
    await state.set_state(States.health_notes)
    await message.delete()


@questionnaire_router.message(States.health_notes, F.text)
async def health_notes(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    await state.update_data(health_notes=message.text)
    await update_user_info(message, state, "client")


@questionnaire_router.message(States.name, F.text)
async def name(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    state_to_set = States.work_experience if data.get("role") == "coach" else States.gender
    await state.set_state(state_to_set)
    text = (
        translate(MessageText.work_experience, data.get("lang"))
        if data["role"] == "coach"
        else translate(MessageText.choose_gender, data.get("lang"))
    )
    reply_markup = choose_gender(data.get("lang")) if data["role"] == "client" else None
    msg = await message.answer(text=text, reply_markup=reply_markup)
    await state.update_data(chat_id=message.chat.id, message_ids=[msg.message_id], name=message.text, verified=False)
    await message.delete()


@questionnaire_router.message(States.work_experience, F.text)
async def work_experience(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    if not all(map(lambda x: x.isdigit(), message.text.split())):
        await message.answer(translate(MessageText.invalid_content, lang=data.get("lang")))
        await message.answer(translate(MessageText.work_experience, lang=data.get("lang")))
        await state.set_state(States.work_experience)
        return

    await state.update_data(work_experience=message.text)
    if data.get("edit_mode"):
        await update_user_info(message, state, "coach")
        return

    additional_info_msg = await message.answer(translate(MessageText.additional_info, lang=data.get("lang")))
    await state.update_data(chat_id=message.chat.id, message_ids=[additional_info_msg.message_id])
    await state.set_state(States.additional_info)
    await message.delete()


@questionnaire_router.message(States.additional_info, F.text)
async def additional_info(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await delete_messages(state)
    await state.update_data(additional_info=message.text)
    if data.get("edit_mode"):
        await update_user_info(message, state, "coach")
        return

    payment_details_msg = await message.answer(translate(MessageText.payment_details, lang=data.get("lang")))
    await state.update_data(chat_id=message.chat.id, message_ids=[payment_details_msg.message_id])
    await state.set_state(States.payment_details)
    await message.delete()


@questionnaire_router.message(States.payment_details, F.text)
async def payment_details(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await delete_messages(state)
    card_number = message.text.replace(" ", "")
    if not all(map(lambda x: x.isdigit(), card_number)) or len(card_number) != 16:
        await message.answer(translate(MessageText.invalid_content, lang=data.get("lang")))
        await message.delete()
        return

    if data.get("edit_mode"):
        await update_user_info(message, state, "coach")
        return

    await state.update_data(payment_details=message.text.replace(" ", ""))
    photo_msg = await message.answer(translate(MessageText.upload_photo, lang=data.get("lang")))
    await state.update_data(chat_id=message.chat.id, message_ids=[photo_msg.message_id])
    await state.set_state(States.profile_photo)
    await message.delete()


@questionnaire_router.message(States.profile_photo, F.photo)
async def profile_photo(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    local_file = await avatar_manager.save_profile_photo(message)

    if local_file and avatar_manager.check_file_size(f"temp/{local_file}", 20):
        if avatar_manager.upload_image_to_gcs(local_file):
            uploaded_msg = await message.answer(translate(MessageText.photo_uploaded, lang=data.get("lang")))
            await state.update_data(
                profile_photo=local_file, chat_id=message.chat.id, message_ids=[uploaded_msg.message_id]
            )
            avatar_manager.clean_up_local_file(local_file)
            await update_user_info(message, state, "coach")
        else:
            await message.answer(translate(MessageText.photo_upload_fail, lang=data.get("lang")))
            await state.set_state(States.profile_photo)
    else:
        await message.answer(translate(MessageText.photo_upload_fail, lang=data.get("lang")))
        await state.set_state(States.profile_photo)


@questionnaire_router.callback_query(States.edit_profile)
async def update_profile(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    await delete_messages(state)
    await state.update_data(lang=profile.language)
    if callback_query.data == "back":
        await show_main_menu(callback_query.message, profile, state)
        return

    state_to_set, message = get_state_and_message(callback_query.data, profile.language)
    await state.update_data(edit_mode=True)
    reply_markup = workout_experience_keyboard(profile.language) if state_to_set == States.workout_experience else None
    await callback_query.message.answer(message, lang=profile.language, reply_markup=reply_markup)
    await state.set_state(state_to_set)
    await callback_query.message.delete()


@questionnaire_router.callback_query(States.workout_type)
async def workout_type(callback_query: CallbackQuery, state: FSMContext):
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    await state.update_data(workout_type=callback_query.data)
    data = await state.get_data()
    coach = Coach.from_dict(data.get("coach"))
    client = Client.from_dict(data.get("client"))
    if data.get("new_client"):
        await client_request(coach, client, state)
        await callback_query.answer(translate(MessageText.coach_selected).format(name=coach.name), show_alert=True)
        await show_main_menu(callback_query.message, profile, state)
    else:
        await callback_query.answer()
        if data.get("request_type") == "subscription":
            await state.set_state(States.workout_days)
            await callback_query.message.answer(
                translate(MessageText.select_days, profile.language), reply_markup=select_days(profile.language, [])
            )
        elif data.get("request_type") == "program":
            kb = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="💰", callback_data=data.get("request_type"))]]
            )
            await callback_query.message.answer("click to pay 👇", reply_markup=kb)
            await state.update_data(price=50)
            await state.set_state(States.handle_payment)
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


@questionnaire_router.callback_query(States.workout_days)
async def workout_days(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    data = await state.get_data()
    days = data.get("workout_days", [])

    if callback_query.data == "complete":
        if days:
            await callback_query.answer(translate(MessageText.saved, lang=profile.language))
            subscription = user_service.storage.get_subscription(profile.id)
            await state.update_data(workout_days=days)
            if data.get("edit_mode"):
                subscription_data = subscription.to_dict()
                exercises = subscription_data.get("exercises", {})
                updated_exercises = {days[i]: exercises for i, exercises in enumerate(exercises.values())}
                subscription_data.update(user=profile.id, exercises=updated_exercises)
                user_service.storage.save_subscription(profile.id, subscription_data)
                await user_service.update_subscription(subscription_data.get("id"), subscription_data)
                await state.set_state(States.show_subscription)
                await show_subscription_page(callback_query, state, subscription)
                with suppress(TelegramBadRequest):
                    await callback_query.message.delete()
            else:
                await callback_query.answer()
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="💰", callback_data=data.get("request_type"))]]
                )  # TODO: REPLACE WITH PAYMENT LINK
                await callback_query.message.answer("click to pay 👇", reply_markup=kb)
                await state.update_data(price=50)
                await state.set_state(States.handle_payment)
                await callback_query.message.delete()
        else:
            await callback_query.answer("❌")
    else:
        if callback_query.data not in days:
            days.append(callback_query.data)
        else:
            await callback_query.answer("❌")

        await state.update_data(workout_days=days)
        reply_markup = select_days(profile.language, days)

        if callback_query.message.reply_markup != reply_markup:
            await callback_query.message.edit_reply_markup(reply_markup=reply_markup)

        await state.set_state(States.workout_days)
