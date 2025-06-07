from contextlib import suppress
from typing import cast

from aiogram import Router, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from dependency_injector.wiring import inject, Provide
from loguru import logger

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
from core.containers import App
from core.exceptions import ProfileNotFoundError, ClientNotFoundError
from core.schemas import Profile
from core.services import APIService
from bot.utils.chat import client_request
from bot.utils.workout_plans import process_new_subscription, edit_subscription_days
from bot.utils.menus import show_main_menu, show_my_profile_menu
from bot.utils.profiles import update_profile_data, check_assigned_clients
from bot.utils.text import get_state_and_message
from bot.utils.other import delete_messages, generate_order_id, set_bot_commands, answer_msg, del_msg, parse_price
from bot.texts.text_manager import msg_text
from core.services.outer import avatar_manager

questionnaire_router = Router()


@questionnaire_router.callback_query(States.select_language)
@inject
async def select_language(
    callback_query: CallbackQuery,
    state: FSMContext,
    bot: Bot = Provide[App.bot],
) -> None:
    await callback_query.answer()
    await delete_messages(state)
    lang = callback_query.data or Settings.DEFAULT_LANG
    await set_bot_commands(bot, lang)
    try:
        profile = await APIService.profile.get_profile_by_tg_id(callback_query.from_user.id)
        if profile:
            await APIService.profile.update_profile(profile.id, {"language": lang})
            await Cache.profile.update_profile(callback_query.from_user.id, dict(language=lang))
            message = callback_query.message
            if message is not None:
                await show_main_menu(cast(Message, message), profile, state)
        else:
            raise ProfileNotFoundError(callback_query.from_user.id)
    except ProfileNotFoundError:
        account_msg = None
        if callback_query.message is not None:
            account_msg = await answer_msg(
                cast(Message, callback_query.message),
                msg_text("choose_account_type", lang),
                reply_markup=select_status_kb(lang),
            )
        if account_msg is not None and callback_query.message is not None:
            await state.update_data(
                lang=lang,
                message_ids=[account_msg.message_id],
                chat_id=callback_query.message.chat.id,
            )
        await state.set_state(States.account_type)

    await del_msg(cast(Message | CallbackQuery | None, callback_query))


@questionnaire_router.callback_query(States.account_type)
async def profile_status_choice(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    data = await state.get_data()
    await delete_messages(state)
    lang = data.get("lang", Settings.DEFAULT_LANG)
    status = callback_query.data if callback_query.data in ("coach", "client") else "client"
    profile = await APIService.profile.create_profile(tg_id=callback_query.from_user.id, status=status, language=lang)
    if profile is None:
        await callback_query.answer(msg_text("unexpected_error", lang), show_alert=True)
        return

    await Cache.profile.save_profile(callback_query.from_user.id, dict(id=profile.id, status=status, language=lang))
    await state.update_data(profile=profile.model_dump())
    if callback_query.message is not None:
        msg = await answer_msg(cast(Message, callback_query.message), msg_text("name", lang))
        if msg is not None:
            await state.update_data(chat_id=callback_query.message.chat.id, message_ids=[msg.message_id], status=status)
    await state.set_state(States.name)


@questionnaire_router.message(States.name)
async def name(message: Message, state: FSMContext) -> None:
    if not message.text:
        return

    await delete_messages(state)
    data = await state.get_data()
    lang = data.get("lang", Settings.DEFAULT_LANG)
    text = msg_text("surname", lang) if data.get("status") == "coach" else msg_text("choose_gender", lang)
    reply_markup = select_gender_kb(lang) if data.get("status") == "client" else None
    msg = await answer_msg(message, text=text, reply_markup=reply_markup)
    await state.update_data(chat_id=message.chat.id, message_ids=[msg.message_id] if msg else [], name=message.text)
    state_to_set = States.surname if data.get("status") == "coach" else States.gender
    await state.set_state(state_to_set)
    await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.callback_query(States.gender)
async def gender(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang", Settings.DEFAULT_LANG)
    await callback_query.answer(msg_text("saved", lang))
    msg = None
    if callback_query.message is not None:
        msg = await answer_msg(cast(Message, callback_query.message), msg_text("born_in", lang))
    await state.update_data(
        gender=callback_query.data,
        chat_id=callback_query.message.chat.id if callback_query.message else 0,
        message_ids=[msg.message_id] if msg else [],
    )
    await del_msg(cast(Message | CallbackQuery | None, callback_query))
    await state.set_state(States.born_in)


@questionnaire_router.message(States.born_in)
async def born_in(message: Message, state: FSMContext) -> None:
    if not message.text:
        return

    await delete_messages(state)
    data = await state.get_data()
    lang = data.get("lang", Settings.DEFAULT_LANG)
    msg = await answer_msg(message, msg_text("workout_goals", lang))
    await state.update_data(born_in=message.text, chat_id=message.chat.id, message_ids=[msg.message_id] if msg else [])
    await state.set_state(States.workout_goals)
    await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.message(States.workout_goals)
async def workout_goals(message: Message, state: FSMContext) -> None:
    if not message.text:
        return

    await delete_messages(state)
    await state.update_data(workout_goals=message.text)
    data = await state.get_data()
    if data.get("edit_mode"):
        await update_profile_data(cast(Message, message), state, "client")
        return

    lang = data.get("lang", Settings.DEFAULT_LANG)
    msg = await answer_msg(
        message,
        msg_text("workout_experience", lang),
        reply_markup=workout_experience_kb(lang),
    )
    await state.update_data(chat_id=message.chat.id, message_ids=[msg.message_id] if msg else [])
    await state.set_state(States.workout_experience)
    await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.callback_query(States.workout_experience)
async def workout_experience(callback_query: CallbackQuery, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    lang = data.get("lang", Settings.DEFAULT_LANG)
    await callback_query.answer(msg_text("saved", lang))
    await state.update_data(workout_experience=callback_query.data)
    if data.get("edit_mode"):
        if callback_query.message is not None:
            await update_profile_data(cast(Message, callback_query.message), state, "client")
        return

    if callback_query.message is not None:
        msg = await answer_msg(cast(Message, callback_query.message), msg_text("weight", lang))
        await state.update_data(chat_id=callback_query.message.chat.id, message_ids=[msg.message_id] if msg else [])
    await state.set_state(States.weight)
    await del_msg(cast(Message | CallbackQuery | None, callback_query))


@questionnaire_router.message(States.weight)
async def weight(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang", Settings.DEFAULT_LANG)
    await delete_messages(state)

    if not message.text or not all(x.isdigit() for x in message.text.split()):
        await answer_msg(message, msg_text("invalid_content", lang))
        await state.set_state(States.weight)
        return

    await state.update_data(weight=message.text)
    if data.get("edit_mode"):
        await update_profile_data(cast(Message, message), state, "client")
        return

    msg = await answer_msg(message, msg_text("health_notes", lang))
    await state.update_data(chat_id=message.chat.id, message_ids=[msg.message_id] if msg else [])
    await state.set_state(States.health_notes)
    await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.message(States.health_notes)
async def health_notes(message: Message, state: FSMContext) -> None:
    if not message.text:
        return

    await delete_messages(state)
    await state.update_data(health_notes=message.text)
    await update_profile_data(cast(Message, message), state, "client")


@questionnaire_router.message(States.surname)
async def surname(message: Message, state: FSMContext) -> None:
    if not message.text:
        return

    await delete_messages(state)
    data = await state.get_data()
    lang = data.get("lang", Settings.DEFAULT_LANG)
    await state.update_data(surname=message.text)
    if data.get("edit_mode"):
        await update_profile_data(cast(Message, message), state, "coach")
        return

    msg = await answer_msg(message, msg_text("work_experience", lang))
    await state.update_data(chat_id=message.chat.id, message_ids=[msg.message_id] if msg else [])
    await state.set_state(States.work_experience)
    await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.message(States.work_experience)
async def work_experience(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang", Settings.DEFAULT_LANG)
    await delete_messages(state)

    if not message.text or not all(x.isdigit() for x in message.text.split()):
        await answer_msg(message, msg_text("invalid_content", lang))
        await answer_msg(message, msg_text("work_experience", lang))
        await state.set_state(States.work_experience)
        return

    await state.update_data(work_experience=message.text)
    if data.get("edit_mode"):
        await update_profile_data(cast(Message, message), state, "coach")
        return

    msg = await answer_msg(message, msg_text("additional_info", lang))
    await state.update_data(chat_id=message.chat.id, message_ids=[msg.message_id] if msg else [])
    await state.set_state(States.additional_info)
    await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.message(States.additional_info)
async def additional_info(message: Message, state: FSMContext) -> None:
    if not message.text:
        return

    data = await state.get_data()
    lang = data.get("lang", Settings.DEFAULT_LANG)
    await delete_messages(state)
    await state.update_data(additional_info=message.text)
    if data.get("edit_mode"):
        await update_profile_data(cast(Message, message), state, "coach")
        return

    msg = await answer_msg(message, msg_text("payment_details", lang))
    await state.update_data(chat_id=message.chat.id, message_ids=[msg.message_id] if msg else [])
    await state.set_state(States.payment_details)
    await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.message(States.payment_details)
async def payment_details(message: Message, state: FSMContext) -> None:
    if not message.text:
        return

    await state.update_data(payment_details=message.text.replace(" ", ""))

    data = await state.get_data()
    lang = data.get("lang", Settings.DEFAULT_LANG)
    await delete_messages(state)
    card_number = message.text.replace(" ", "")
    if not all(x.isdigit() for x in card_number) or len(card_number) != 16:
        await answer_msg(message, msg_text("invalid_content", lang))
        await del_msg(cast(Message | CallbackQuery | None, message))
        return

    if data.get("edit_mode"):
        await update_profile_data(cast(Message, message), state, "coach")
        return

    msg = await answer_msg(message, msg_text("enter_program_price", lang))
    await state.update_data(chat_id=message.chat.id, message_ids=[msg.message_id] if msg else [])
    await state.set_state(States.program_price)
    await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.message(States.program_price)
async def enter_program_price(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    lang = data.get("lang", Settings.DEFAULT_LANG)
    if not message.text:
        await answer_msg(message, msg_text("invalid_content", lang))
        await del_msg(message)
        return

    try:
        price = parse_price(message.text)
    except ValueError:
        await answer_msg(message, msg_text("invalid_content", lang))
        await del_msg(message)
        return

    if data.get("edit_mode"):
        await state.update_data(program_price=str(price))
        await update_profile_data(cast(Message, message), state, "coach")
        return

    msg = await answer_msg(message, msg_text("enter_subscription_price", lang))
    await state.update_data(
        program_price=str(price),
        message_ids=[msg.message_id] if msg else [],
        chat_id=message.chat.id,
    )
    await state.set_state(States.subscription_price)
    await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.message(States.subscription_price)
async def enter_subscription_price(message: Message, state: FSMContext) -> None:
    await delete_messages(state)
    data = await state.get_data()
    lang = data.get("lang", Settings.DEFAULT_LANG)
    if not message.text:
        await answer_msg(message, msg_text("invalid_content", lang))
        await del_msg(message)
        return

    try:
        price = parse_price(message.text)
    except ValueError:
        await answer_msg(message, msg_text("invalid_content", lang))
        await del_msg(message)
        return

    if data.get("edit_mode"):
        await state.update_data(subscription_price=str(price))
        await update_profile_data(cast(Message, message), state, "coach")
        return

    msg = await answer_msg(message, msg_text("upload_photo", lang))
    await state.update_data(
        subscription_price=str(price),
        chat_id=message.chat.id,
        message_ids=[msg.message_id] if msg else [],
    )
    await state.set_state(States.profile_photo)
    await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.message(States.profile_photo)
async def profile_photo(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await answer_msg(message, msg_text("invalid_content", Settings.DEFAULT_LANG))
        return

    await delete_messages(state)
    data = await state.get_data()
    lang = data.get("lang", Settings.DEFAULT_LANG)
    local_file = await avatar_manager.save_image(message)

    if local_file and avatar_manager.check_file_size(local_file, 20):
        if avatar_manager.load_file_to_bucket(local_file):
            msg = await answer_msg(message, msg_text("photo_uploaded", lang))
            if msg:
                await state.update_data(profile_photo=local_file, chat_id=message.chat.id, message_ids=[msg.message_id])
            avatar_manager.clean_up_file(local_file)
            await update_profile_data(cast(Message, message), state, "coach")
        else:
            await answer_msg(message, msg_text("photo_upload_fail", lang))
            await state.set_state(States.profile_photo)
    else:
        await answer_msg(message, msg_text("photo_upload_fail", lang))
        await state.set_state(States.profile_photo)


@questionnaire_router.callback_query(States.edit_profile)
async def update_profile(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    await delete_messages(state)
    await state.update_data(lang=profile.language or Settings.DEFAULT_LANG)
    if callback_query.data == "back":
        message = callback_query.message
        if message is not None:
            await show_main_menu(cast(Message, message), profile, state)
        return

    state_to_set, message_text = get_state_and_message(
        callback_query.data or "", profile.language or Settings.DEFAULT_LANG
    )
    if state_to_set == States.subscription_price:
        msg = None
        if callback_query.message is not None:
            msg = await answer_msg(
                cast(Message, callback_query.message),
                msg_text("price_warning", profile.language or Settings.DEFAULT_LANG),
            )
        if msg and callback_query.message:
            await state.update_data(price_warning_msg_ids=[msg.message_id], chat_id=callback_query.message.chat.id)
    await state.update_data(edit_mode=True)
    reply_markup = (
        workout_experience_kb(profile.language or Settings.DEFAULT_LANG)
        if state_to_set == States.workout_experience
        else None
    )
    if callback_query.message is not None:
        await answer_msg(cast(Message, callback_query.message), message_text, reply_markup=reply_markup)
    await state.set_state(state_to_set)
    await del_msg(cast(Message | CallbackQuery | None, callback_query))


@questionnaire_router.callback_query(States.workout_type)
async def workout_type(callback_query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    await state.update_data(workout_type=callback_query.data)
    await state.set_state(States.enter_wishes)
    if callback_query.message is not None:
        await answer_msg(
            cast(Message, callback_query.message), msg_text("enter_wishes", profile.language or Settings.DEFAULT_LANG)
        )
    await del_msg(cast(Message | CallbackQuery | None, callback_query))


@questionnaire_router.message(States.enter_wishes)
async def enter_wishes(message: Message, state: FSMContext):
    if not message.text:
        return

    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    client = await Cache.client.get_client(profile.id)

    if not client or not client.assigned_to:
        return

    coach = await Cache.coach.get_coach(client.assigned_to.pop())
    await state.update_data(wishes=message.text, sender_name=client.name)
    data = await state.get_data()

    if data.get("new_client"):
        if message is not None:
            await answer_msg(
                message, msg_text("coach_selected", profile.language or Settings.DEFAULT_LANG).format(name=coach.name)
            )
        await client_request(coach, client, data)
        if message is not None:
            await show_main_menu(cast(Message, message), profile, state)
            await del_msg(cast(Message | CallbackQuery | None, message))
    else:
        if data.get("service_type") == "subscription":
            await state.set_state(States.workout_days)
            if message is not None:
                await answer_msg(
                    message,
                    text=msg_text("select_days", profile.language or Settings.DEFAULT_LANG),
                    reply_markup=select_days_kb(profile.language or Settings.DEFAULT_LANG, []),
                )
        elif data.get("service_type") == "program":
            order_id = generate_order_id()
            await state.update_data(order_id=order_id, amount=coach.program_price)
            payment_link = await APIService.payment.get_payment_link(
                action="pay",
                amount=coach.program_price,
                order_id=order_id,
                payment_type="program",
                client_id=client.id,
            )
            if payment_link:
                await state.set_state(States.handle_payment)
                if message is not None:
                    await answer_msg(
                        message,
                        msg_text("follow_link", profile.language or Settings.DEFAULT_LANG),
                        reply_markup=payment_kb(profile.language or Settings.DEFAULT_LANG, payment_link, "program"),
                    )
            else:
                if message is not None:
                    await answer_msg(message, msg_text("unexpected_error", profile.language or Settings.DEFAULT_LANG))
        if message is not None:
            await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.callback_query(States.workout_days)
async def workout_days(callback_query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    try:
        client = await Cache.client.get_client(profile.id)
    except ClientNotFoundError:
        logger.error(f"Client profile not found for profile {profile.id}")
        await callback_query.answer(msg_text("unexpected_error", profile.language or Settings.DEFAULT_LANG))
        return

    days = data.get("workout_days", [])
    if callback_query.data == "complete":
        if days:
            await state.update_data(workout_days=days)
            if data.get("edit_mode"):
                subscription = await Cache.workout.get_latest_subscription(client.id)
                if subscription and len(subscription.workout_days) == len(days):
                    await edit_subscription_days(callback_query, days, client.id, state, subscription)
                else:
                    if callback_query.message is not None:
                        await answer_msg(
                            cast(Message, callback_query.message),
                            msg_text("workout_plan_delete_warning", profile.language or Settings.DEFAULT_LANG),
                            reply_markup=yes_no_kb(profile.language or Settings.DEFAULT_LANG),
                        )
                    await state.set_state(States.confirm_subscription_reset)
            else:
                await callback_query.answer(msg_text("saved", profile.language or Settings.DEFAULT_LANG))
                await process_new_subscription(callback_query, profile, state)
        else:
            await callback_query.answer("❌")
    else:
        if callback_query.data not in days:
            days.append(callback_query.data)
        else:
            days.remove(callback_query.data)

        await state.update_data(workout_days=days)

        if callback_query.message is not None:
            with suppress(TelegramBadRequest, AttributeError):
                if isinstance(callback_query.message, Message):
                    await callback_query.message.edit_reply_markup(
                        reply_markup=select_days_kb(profile.language or Settings.DEFAULT_LANG, days)
                    )

        await state.set_state(States.workout_days)


@questionnaire_router.callback_query(States.profile_delete)
async def delete_profile_confirmation(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])

    if callback_query.data == "yes":
        if profile and profile.status == "coach":
            if await check_assigned_clients(profile.id):
                await answer_msg(
                    cast(Message | CallbackQuery, callback_query),
                    msg_text("unable_to_delete_profile", profile.language or Settings.DEFAULT_LANG),
                )
                return

        if profile and await APIService.profile.delete_profile(profile.id):
            await Cache.profile.delete_profile(callback_query.from_user.id)
            await answer_msg(
                cast(Message | CallbackQuery, callback_query),
                msg_text("profile_deleted", profile.language or Settings.DEFAULT_LANG),
            )
            await answer_msg(
                cast(Message | CallbackQuery, callback_query),
                msg_text("select_action", profile.language or Settings.DEFAULT_LANG),
            )
            await del_msg(cast(Message | CallbackQuery | None, callback_query))
            await state.clear()
        else:
            await answer_msg(
                cast(Message | CallbackQuery, callback_query),
                msg_text("unexpected_error", profile.language or Settings.DEFAULT_LANG),
            )
    else:
        if callback_query.message is not None:
            await show_my_profile_menu(cast(CallbackQuery, callback_query), profile, state)
