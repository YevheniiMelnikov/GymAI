from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import (
    select_gender_kb,
    payment_kb,
    select_days_kb,
    workout_experience_kb,
    yes_no_kb,
    select_status_kb,
)
from bot.states import States
from config.env_settings import Settings
from core.cache import Cache
from core.exceptions import ProfileNotFoundError
from core.services.gstorage_service import avatar_manager
from functions.chat import client_request
from functions.exercises import edit_subscription_days, process_new_subscription
from functions.menus import show_main_menu, show_my_profile_menu
from functions.profiles import get_user_profile, update_profile_data, check_assigned_clients
from functions.text_utils import get_state_and_message
from functions.utils import delete_messages, generate_order_id, set_bot_commands
from core.services.payment_service import PaymentService
from bot.texts.text_manager import msg_text
from core.services.profile_service import ProfileService

questionnaire_router = Router()


@questionnaire_router.callback_query(States.select_language)
async def select_language(callback_query: CallbackQuery, state: FSMContext) -> None:
    await callback_query.answer()
    await delete_messages(state)
    lang = callback_query.data
    await set_bot_commands(lang)
    try:
        profile = await get_user_profile(callback_query.from_user.id)
        if profile:
            await ProfileService.edit_profile(profile.id, {"language": lang})
            Cache.profile.set_profile_data(callback_query.from_user.id, dict(language=lang))
            profile.language = lang
            await show_main_menu(callback_query.message, profile, state)
        else:
            raise ProfileNotFoundError(callback_query.from_user.id)
    except ProfileNotFoundError:
        account_msg = await callback_query.message.answer(
            msg_text("choose_account_type", lang), reply_markup=select_status_kb(lang)
        )
        await state.update_data(lang=lang, message_ids=[account_msg.message_id], chat_id=callback_query.message.chat.id)
        await state.set_state(States.account_type)

    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


@questionnaire_router.callback_query(States.account_type)
async def profile_status_choice(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    data = await state.get_data()
    await delete_messages(state)
    lang = data.get("lang", Settings.BOT_LANG)
    status = callback_query.data if callback_query.data in ["coach", "client"] else "client"
    profile = await ProfileService.create_profile(telegram_id=callback_query.from_user.id, status=status, language=lang)
    if not profile:
        await callback_query.message.answer(msg_text("unexpected_error", lang))
        return

    Cache.profile.set_profile_data(callback_query.from_user.id, dict(id=profile.id, status=status, language=lang))
    name_msg = await callback_query.message.answer(msg_text("name", lang))
    await state.update_data(chat_id=callback_query.message.chat.id, message_ids=[name_msg.message_id], status=status)
    await state.set_state(States.name)


@questionnaire_router.message(States.name, F.text)
async def name(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    state_to_set = States.surname if data.get("status") == "coach" else States.gender
    await state.set_state(state_to_set)
    text = (
        msg_text("surname", data.get("lang"))
        if data["status"] == "coach"
        else msg_text("choose_gender", data.get("lang"))
    )
    reply_markup = select_gender_kb(data.get("lang")) if data["status"] == "client" else None
    msg = await message.answer(text=text, reply_markup=reply_markup)
    await state.update_data(chat_id=message.chat.id, message_ids=[msg.message_id], name=message.text)
    await message.delete()


@questionnaire_router.callback_query(States.gender)
async def gender(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await callback_query.answer(msg_text("saved", data.get("lang")))
    age_msg = await callback_query.message.answer(msg_text("born_in", data.get("lang")))
    await state.update_data(
        gender=callback_query.data, chat_id=callback_query.message.chat.id, message_ids=[age_msg.message_id]
    )
    await callback_query.message.delete()
    await state.set_state(States.born_in)


@questionnaire_router.message(States.born_in, F.text)
async def born_in(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    goals_msg = await message.answer(msg_text("workout_goals", data.get("lang")))
    await state.update_data(born_in=message.text, chat_id=message.chat.id, message_ids=[goals_msg.message_id])
    await state.set_state(States.workout_goals)
    await message.delete()


@questionnaire_router.message(States.workout_goals, F.text)
async def workout_goals(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    await state.update_data(workout_goals=message.text)
    data = await state.get_data()
    if data.get("edit_mode"):
        await update_profile_data(message, state, "client")
        return

    experience_msg = await message.answer(
        msg_text("workout_experience", data.get("lang")),
        reply_markup=workout_experience_kb(data.get("lang")),
    )
    await state.update_data(chat_id=message.chat.id, message_ids=[experience_msg.message_id])
    await state.set_state(States.workout_experience)
    await message.delete()


@questionnaire_router.callback_query(States.workout_experience)
async def workout_experience(callback_query: CallbackQuery, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    await callback_query.answer(msg_text("saved", data.get("lang")))
    await state.update_data(workout_experience=callback_query.data)
    if data.get("edit_mode"):
        await update_profile_data(callback_query.message, state, "client")
        return

    weight_msg = await callback_query.message.answer(msg_text("weight", data.get("lang")))
    await state.update_data(chat_id=callback_query.message.chat.id, message_ids=[weight_msg.message_id])
    await state.set_state(States.weight)
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


@questionnaire_router.message(States.weight, F.text)
async def weight(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await delete_messages(state)
    if not all(map(lambda x: x.isdigit(), message.text.split())):
        await message.answer(msg_text("invalid_content", data.get("lang")))
        await state.set_state(States.weight)
        return

    await state.update_data(weight=message.text)
    if data.get("edit_mode"):
        await update_profile_data(message, state, "client")
        return

    health_msg = await message.answer(msg_text("health_notes", data.get("lang")))
    await state.update_data(chat_id=message.chat.id, message_ids=[health_msg.message_id])
    await state.set_state(States.health_notes)
    await message.delete()


@questionnaire_router.message(States.health_notes, F.text)
async def health_notes(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    await state.update_data(health_notes=message.text)
    await update_profile_data(message, state, "client")


@questionnaire_router.message(States.surname, F.text)
async def surname(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    await state.update_data(surname=message.text)
    if data.get("edit_mode"):
        await update_profile_data(message, state, "coach")
        return

    work_experience_msg = await message.answer(msg_text("work_experience", data.get("lang")))
    await state.update_data(chat_id=message.chat.id, message_ids=[work_experience_msg.message_id])
    await state.set_state(States.work_experience)
    await message.delete()


@questionnaire_router.message(States.work_experience, F.text)
async def work_experience(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    if not all(map(lambda x: x.isdigit(), message.text.split())):
        await message.answer(msg_text("invalid_content", data.get("lang")))
        await message.answer(msg_text("work_experience", data.get("lang")))
        await state.set_state(States.work_experience)
        return

    await state.update_data(work_experience=message.text)
    if data.get("edit_mode"):
        await update_profile_data(message, state, "coach")
        return

    additional_info_msg = await message.answer(msg_text("additional_info", data.get("lang")))
    await state.update_data(chat_id=message.chat.id, message_ids=[additional_info_msg.message_id])
    await state.set_state(States.additional_info)
    await message.delete()


@questionnaire_router.message(States.additional_info, F.text)
async def additional_info(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await delete_messages(state)
    await state.update_data(additional_info=message.text)
    if data.get("edit_mode"):
        await update_profile_data(message, state, "coach")
        return

    payment_details_msg = await message.answer(msg_text("payment_details", data.get("lang")))
    await state.update_data(chat_id=message.chat.id, message_ids=[payment_details_msg.message_id])
    await state.set_state(States.payment_details)
    await message.delete()


@questionnaire_router.message(States.payment_details, F.text)
async def payment_details(message: Message, state: FSMContext) -> None:
    await state.update_data(payment_details=message.text.replace(" ", ""))
    data = await state.get_data()
    await delete_messages(state)
    card_number = message.text.replace(" ", "")
    if not all(map(lambda x: x.isdigit(), card_number)) or len(card_number) != 16:
        await message.answer(msg_text("invalid_content", data.get("lang")))
        await message.delete()
        return

    if data.get("edit_mode"):
        await update_profile_data(message, state, "coach")
        return

    program_price_msg = await message.answer(msg_text("enter_program_price", data.get("lang")))
    await state.update_data(chat_id=message.chat.id, message_ids=[program_price_msg.message_id])
    await state.set_state(States.program_price)
    await message.delete()


@questionnaire_router.message(States.program_price, F.text)
async def enter_program_price(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    if not all(map(lambda x: x.isdigit(), message.text)):
        await message.answer(msg_text("invalid_content", data.get("lang")))
        await message.delete()
        return

    if data.get("edit_mode"):
        await state.update_data(program_price=message.text)
        await update_profile_data(message, state, "coach")
        return

    subscription_price_msg = await message.answer(msg_text("enter_subscription_price", data.get("lang")))
    await state.update_data(
        program_price=message.text, message_ids=[subscription_price_msg.message_id], chat_id=message.chat.id
    )
    await state.set_state(States.subscription_price)
    await message.delete()


@questionnaire_router.message(States.subscription_price, F.text)
async def enter_subscription_price(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    if not all(map(lambda x: x.isdigit(), message.text)):
        await message.answer(msg_text("invalid_content", data.get("lang")))
        await message.delete()
        return

    if data.get("edit_mode"):
        await state.update_data(subscription_price=message.text)
        await update_profile_data(message, state, "coach")
        return

    photo_msg = await message.answer(msg_text("upload_photo", data.get("lang")))
    await state.update_data(
        subscription_price=message.text, chat_id=message.chat.id, message_ids=[photo_msg.message_id]
    )
    await state.set_state(States.profile_photo)
    await message.delete()


@questionnaire_router.message(States.profile_photo, F.photo)
async def profile_photo(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    local_file = await avatar_manager.save_image(message)

    if local_file and avatar_manager.check_file_size(local_file, 20):
        if avatar_manager.load_file_to_bucket(local_file):
            uploaded_msg = await message.answer(msg_text("photo_uploaded", data.get("lang")))
            await state.update_data(
                profile_photo=local_file, chat_id=message.chat.id, message_ids=[uploaded_msg.message_id]
            )
            avatar_manager.clean_up_file(local_file)
            await update_profile_data(message, state, "coach")
        else:
            await message.answer(msg_text("photo_upload_fail", data.get("lang")))
            await state.set_state(States.profile_photo)
    else:
        await message.answer(msg_text("photo_upload_fail", data.get("lang")))
        await state.set_state(States.profile_photo)


@questionnaire_router.callback_query(States.edit_profile)
async def update_profile(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile = await get_user_profile(callback_query.from_user.id)
    await delete_messages(state)
    await state.update_data(lang=profile.language)
    if callback_query.data == "back":
        await show_main_menu(callback_query.message, profile, state)
        return

    state_to_set, message_text = get_state_and_message(callback_query.data, profile.language)
    if state_to_set == States.subscription_price:
        price_warning_msg = await callback_query.message.answer(msg_text("price_warning", profile.language))
        await state.update_data(
            price_warning_msg_ids=[price_warning_msg.message_id], chat_id=callback_query.message.chat.id
        )
    await state.update_data(edit_mode=True)
    reply_markup = workout_experience_kb(profile.language) if state_to_set == States.workout_experience else None
    await callback_query.message.answer(message_text, lang=profile.language, reply_markup=reply_markup)
    await state.set_state(state_to_set)
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


@questionnaire_router.callback_query(States.workout_type)
async def workout_type(callback_query: CallbackQuery, state: FSMContext):
    profile = await get_user_profile(callback_query.from_user.id)
    await state.update_data(workout_type=callback_query.data)
    await state.set_state(States.enter_wishes)
    await callback_query.message.answer(msg_text("enter_wishes", profile.language))
    await callback_query.message.delete()


@questionnaire_router.message(States.enter_wishes)
async def enter_wishes(message: Message, state: FSMContext):
    profile = await get_user_profile(message.from_user.id)
    client = Cache.client.get_client(profile.id)
    coach = Cache.coach.get_coach(client.assigned_to.pop())
    await state.update_data(wishes=message.text, sender_name=client.name)
    data = await state.get_data()

    if data.get("new_client"):
        await message.answer(msg_text("coach_selected", profile.language).format(name=coach.name))
        await client_request(coach, client, data)
        await show_main_menu(message, profile, state)
        with suppress(TelegramBadRequest):
            await message.delete()
    else:
        if data.get("request_type") == "subscription":
            await state.set_state(States.workout_days)
            await message.answer(
                text=msg_text("select_days", profile.language), reply_markup=select_days_kb(profile.language, [])
            )
        elif data.get("request_type") == "program":
            order_id = generate_order_id()
            await state.update_data(order_id=order_id, amount=coach.program_price)
            if payment_link := await PaymentService.get_payment_link(
                action="pay",
                amount=str(coach.program_price),
                order_id=order_id,
                payment_type="program",
                profile_id=profile.id,
            ):
                await state.set_state(States.handle_payment)
                await message.answer(
                    msg_text("follow_link", profile.language),
                    reply_markup=payment_kb(profile.language, payment_link, "program"),
                )
            else:
                await message.answer(msg_text("unexpected_error", profile.language))
        with suppress(TelegramBadRequest):
            await message.delete()


@questionnaire_router.callback_query(States.workout_days)
async def workout_days(callback_query: CallbackQuery, state: FSMContext):
    profile = await get_user_profile(callback_query.from_user.id)
    data = await state.get_data()
    days = data.get("workout_days", [])

    if callback_query.data == "complete":
        if days:
            await state.update_data(workout_days=days)
            if data.get("edit_mode"):
                subscription = Cache.workout.get_subscription(profile.id)
                if len(subscription.workout_days) == len(days):
                    await edit_subscription_days(callback_query, days, profile, state, subscription)
                else:
                    await callback_query.message.answer(
                        msg_text("workout_plan_delete_warning", profile.language),
                        reply_markup=yes_no_kb(profile.language),
                    )
                    await state.set_state(States.confirm_subscription_reset)
            else:
                await callback_query.answer(msg_text("saved", profile.language))
                await process_new_subscription(callback_query, profile, state)
        else:
            await callback_query.answer("❌")
    else:
        if callback_query.data not in days:
            days.append(callback_query.data)
        else:
            days.remove(callback_query.data)

        await state.update_data(workout_days=days)

        with suppress(TelegramBadRequest):
            await callback_query.message.edit_reply_markup(reply_markup=select_days_kb(profile.language, days))

        await state.set_state(States.workout_days)


@questionnaire_router.callback_query(States.profile_delete)
async def delete_profile_confirmation(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile = await get_user_profile(callback_query.from_user.id)

    if callback_query.data == "yes":
        if profile and profile.status == "coach":
            if await check_assigned_clients(profile.id):
                await callback_query.answer(msg_text("unable_to_delete_profile", profile.language))
                return

        if profile and await ProfileService.delete_profile(profile.id):
            Cache.profile.delete_profile(callback_query.from_user.id)
            await callback_query.message.answer(msg_text("profile_deleted", profile.language))
            await callback_query.message.answer(msg_text("select_action", profile.language))
            await callback_query.message.delete()
            await state.clear()

        else:
            await callback_query.message.answer(msg_text("unexpected_error", profile.language))
    else:
        await show_my_profile_menu(callback_query, profile, state)
