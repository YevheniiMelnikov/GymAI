from contextlib import suppress
from typing import cast
import os
from decimal import Decimal

from aiogram import Router, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from bot.keyboards import (
    select_gender_kb,
    select_days_kb,
    workout_experience_kb,
    yes_no_kb,
    select_role_kb,
    select_language_kb,
)
from bot.states import States
from config.app_settings import settings
from core.cache import Cache
from core.enums import ClientStatus, Language
from core.exceptions import ProfileNotFoundError, ClientNotFoundError
from core.schemas import Profile, Client
from core.services import APIService
from bot.utils.chat import client_request
from bot.utils.credits import required_credits
from bot.utils.workout_plans import process_new_subscription, edit_subscription_days
from bot.utils.menus import show_main_menu, show_my_profile_menu, send_policy_confirmation, show_balance_menu
from bot.utils.profiles import update_profile_data, check_assigned_clients, get_assigned_coach
from core.enums import CoachType
from bot.utils.text import get_state_and_message
from bot.utils.other import parse_price
from bot.utils.bot import del_msg, answer_msg, delete_messages, set_bot_commands
from bot.texts.text_manager import msg_text
from core.services import get_avatar_manager
from core.utils.validators import is_valid_year

questionnaire_router = Router()


@questionnaire_router.callback_query(States.select_language)
async def select_language(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await callback_query.answer()
    await delete_messages(state)
    lang = callback_query.data or settings.DEFAULT_LANG
    await set_bot_commands(bot, lang)
    try:
        profile = await APIService.profile.get_profile_by_tg_id(callback_query.from_user.id)
        if profile:
            await APIService.profile.update_profile(profile.id, {"language": lang})
            await Cache.profile.update_profile(callback_query.from_user.id, dict(language=lang))
            profile.language = cast(Language, lang)
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
                reply_markup=select_role_kb(lang),
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
async def profile_role_choice(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    data = await state.get_data()
    await delete_messages(state)
    lang = data.get("lang", settings.DEFAULT_LANG)
    role = callback_query.data if callback_query.data in ("coach", "client") else "client"
    profile = await APIService.profile.create_profile(tg_id=callback_query.from_user.id, role=role, language=lang)
    if profile is None:
        await callback_query.answer(msg_text("unexpected_error", lang), show_alert=True)
        return

    await Cache.profile.save_profile(callback_query.from_user.id, dict(id=profile.id, role=role, language=lang))
    await state.update_data(profile=profile.model_dump())
    if callback_query.message is not None:
        msg = await answer_msg(cast(Message, callback_query.message), msg_text("name", lang))
        if msg is not None:
            await state.update_data(chat_id=callback_query.message.chat.id, message_ids=[msg.message_id], role=role)
    await state.set_state(States.name)


@questionnaire_router.message(States.name)
async def name(message: Message, state: FSMContext) -> None:
    if not message.text:
        return

    await delete_messages(state)
    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)
    text = msg_text("surname", lang) if data.get("role") == "coach" else msg_text("choose_gender", lang)
    reply_markup = select_gender_kb(lang) if data.get("role") == "client" else None
    msg = await answer_msg(message, text=text, reply_markup=reply_markup)
    await state.update_data(chat_id=message.chat.id, message_ids=[msg.message_id] if msg else [], name=message.text)
    state_to_set = States.surname if data.get("role") == "coach" else States.gender
    await state.set_state(state_to_set)
    await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.callback_query(States.gender)
async def gender(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)
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
async def born_in(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.text:
        return

    await delete_messages(state)
    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)
    if not is_valid_year(message.text):
        await answer_msg(message, msg_text("invalid_content", lang))
        return

    await state.update_data(
        born_in=message.text,
        chat_id=message.chat.id,
        status=ClientStatus.initial,
    )
    await send_policy_confirmation(cast(Message, message), state)
    await state.set_state(States.accept_policy)


@questionnaire_router.message(States.workout_goals)
async def workout_goals(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.text:
        return

    await delete_messages(state)
    await state.update_data(workout_goals=message.text)
    data = await state.get_data()
    if data.get("edit_mode"):
        await update_profile_data(cast(Message, message), state, "client", bot)
        return

    lang = data.get("lang", settings.DEFAULT_LANG)
    msg = await answer_msg(
        message,
        msg_text("workout_experience", lang),
        reply_markup=workout_experience_kb(lang),
    )
    await state.update_data(chat_id=message.chat.id, message_ids=[msg.message_id] if msg else [])
    await state.set_state(States.workout_experience)
    await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.callback_query(States.workout_experience)
async def workout_experience(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await delete_messages(state)
    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)
    await callback_query.answer(msg_text("saved", lang))
    await state.update_data(workout_experience=callback_query.data)
    if data.get("edit_mode"):
        if callback_query.message is not None:
            await update_profile_data(cast(Message, callback_query.message), state, "client", bot)
        return

    if callback_query.message is not None:
        msg = await answer_msg(cast(Message, callback_query.message), msg_text("weight", lang))
        await state.update_data(chat_id=callback_query.message.chat.id, message_ids=[msg.message_id] if msg else [])
    await state.set_state(States.weight)
    await del_msg(cast(Message | CallbackQuery | None, callback_query))


@questionnaire_router.message(States.weight)
async def weight(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)
    await delete_messages(state)

    if not message.text or not all(x.isdigit() for x in message.text.split()):
        await answer_msg(message, msg_text("invalid_content", lang))
        await state.set_state(States.weight)
        return

    await state.update_data(weight=message.text)
    if data.get("edit_mode"):
        await update_profile_data(cast(Message, message), state, "client", bot)
        return

    msg = await answer_msg(message, msg_text("health_notes", lang))
    await state.update_data(chat_id=message.chat.id, message_ids=[msg.message_id] if msg else [])
    await state.set_state(States.health_notes)
    await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.message(States.health_notes)
async def health_notes(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.text:
        return

    await delete_messages(state)
    data = await state.get_data()
    await state.update_data(health_notes=message.text, status=ClientStatus.default)
    if not data.get("edit_mode"):
        await answer_msg(
            message,
            msg_text("initial_credits_granted", data.get("lang", settings.DEFAULT_LANG)),
        )
        await state.update_data(credits_delta=settings.PACKAGE_START_CREDITS)

    await update_profile_data(cast(Message, message), state, "client", bot)


@questionnaire_router.message(States.surname)
async def surname(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.text:
        return

    await delete_messages(state)
    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)
    await state.update_data(surname=message.text)
    if data.get("edit_mode"):
        await update_profile_data(cast(Message, message), state, "coach", bot)
        return

    msg = await answer_msg(message, msg_text("work_experience", lang))
    await state.update_data(chat_id=message.chat.id, message_ids=[msg.message_id] if msg else [])
    await state.set_state(States.work_experience)
    await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.message(States.work_experience)
async def work_experience(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)
    await delete_messages(state)

    if not message.text or not all(x.isdigit() for x in message.text.split()):
        await answer_msg(message, msg_text("invalid_content", lang))
        await answer_msg(message, msg_text("work_experience", lang))
        await state.set_state(States.work_experience)
        return

    await state.update_data(work_experience=message.text)
    if data.get("edit_mode"):
        await update_profile_data(cast(Message, message), state, "coach", bot)
        return

    msg = await answer_msg(message, msg_text("additional_info", lang))
    await state.update_data(chat_id=message.chat.id, message_ids=[msg.message_id] if msg else [])
    await state.set_state(States.additional_info)
    await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.message(States.additional_info)
async def additional_info(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.text:
        return

    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)
    await delete_messages(state)
    await state.update_data(additional_info=message.text)
    if data.get("edit_mode"):
        await update_profile_data(cast(Message, message), state, "coach", bot)
        return

    msg = await answer_msg(message, msg_text("payment_details", lang))
    await state.update_data(chat_id=message.chat.id, message_ids=[msg.message_id] if msg else [])
    await state.set_state(States.payment_details)
    await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.message(States.payment_details)
async def payment_details(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.text:
        return

    await state.update_data(payment_details=message.text.replace(" ", ""))

    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)
    await delete_messages(state)
    card_number = message.text.replace(" ", "")
    if not all(x.isdigit() for x in card_number) or len(card_number) != 16:
        await answer_msg(message, msg_text("invalid_content", lang))
        await del_msg(cast(Message | CallbackQuery | None, message))
        return

    if data.get("edit_mode"):
        await update_profile_data(cast(Message, message), state, "coach", bot)
        return

    msg = await answer_msg(message, msg_text("enter_program_price", lang))
    await state.update_data(chat_id=message.chat.id, message_ids=[msg.message_id] if msg else [])
    await state.set_state(States.program_price)
    await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.message(States.program_price)
async def enter_program_price(message: Message, state: FSMContext, bot: Bot) -> None:
    await delete_messages(state)
    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)
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
        await update_profile_data(cast(Message, message), state, "coach", bot)
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
async def enter_subscription_price(message: Message, state: FSMContext, bot: Bot) -> None:
    await delete_messages(state)
    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)
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
        await update_profile_data(cast(Message, message), state, "coach", bot)
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
async def profile_photo(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.photo:
        await answer_msg(message, msg_text("invalid_content", settings.DEFAULT_LANG))
        return

    await delete_messages(state)
    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)
    avatar_manager = get_avatar_manager()
    local_file = await avatar_manager.save_image(message)

    if local_file and avatar_manager.check_file_size(local_file):
        if avatar_manager.load_file_to_bucket(local_file):
            msg = await answer_msg(message, msg_text("photo_uploaded", lang))
            if msg:
                await state.update_data(
                    profile_photo=os.path.basename(local_file),
                    chat_id=message.chat.id,
                    message_ids=[msg.message_id],
                )
            avatar_manager.clean_up_file(local_file)
            role = data.get("role", "coach")
            if data.get("edit_mode"):
                await update_profile_data(cast(Message, message), state, role, bot)
            else:
                await state.update_data(role=role)
                await send_policy_confirmation(cast(Message, message), state)
                await state.set_state(States.accept_policy)
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
    await state.update_data(lang=profile.language or settings.DEFAULT_LANG)
    if callback_query.data == "back":
        message = callback_query.message
        if message is not None:
            await show_main_menu(cast(Message, message), profile, state)
        return

    state_to_set, message_text = get_state_and_message(
        callback_query.data or "", profile.language or settings.DEFAULT_LANG
    )
    if state_to_set == States.subscription_price:
        msg = None
        if callback_query.message is not None:
            msg = await answer_msg(
                cast(Message, callback_query.message),
                msg_text("price_warning", profile.language or settings.DEFAULT_LANG).format(
                    tg=settings.TG_SUPPORT_CONTACT
                ),
            )
        if msg and callback_query.message:
            await state.update_data(price_warning_msg_ids=[msg.message_id], chat_id=callback_query.message.chat.id)
    await state.update_data(edit_mode=True)
    reply_markup = (
        workout_experience_kb(profile.language or settings.DEFAULT_LANG)
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
    await state.set_state(States.enter_wishes)
    if callback_query.message is not None:
        wishes_msg = await answer_msg(
            cast(Message, callback_query.message), msg_text("enter_wishes", profile.language or settings.DEFAULT_LANG)
        )
        await state.update_data(
            workout_type=callback_query.data,
            chat_id=callback_query.message.chat.id,
            message_ids=[wishes_msg.message_id] if wishes_msg else [],
        )
    await del_msg(cast(Message | CallbackQuery | None, callback_query))


@questionnaire_router.message(States.enter_wishes)
async def enter_wishes(message: Message, state: FSMContext, bot: Bot):
    if not message.text:
        return

    await delete_messages(state)
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])

    # AI coach flow
    if data.get("ai_service"):
        client = Client.model_validate(data.get("client"))
        required = int(data.get("required", 0))
        wishes = message.text
        await state.update_data(wishes=wishes)

        if client.credits < required:
            await answer_msg(message, msg_text("not_enough_credits", profile.language))
            await show_balance_menu(message, profile, state)
            return

        await state.update_data(wishes=wishes)
        await state.set_state(States.ai_confirm_service)
        await answer_msg(
            message,
            msg_text("confirm_service", profile.language).format(
                balance=client.credits,
                price=required,
            ),
            reply_markup=yes_no_kb(profile.language),
        )
        if message is not None:
            await del_msg(cast(Message | CallbackQuery | None, message))
        return

    # Regular coach flow
    client = await Cache.client.get_client(profile.id)

    if not client or not client.assigned_to:
        return

    coach = await get_assigned_coach(client, coach_type=CoachType.human)
    if coach is None:
        return
    await state.update_data(wishes=message.text, sender_name=client.name)
    data = await state.get_data()

    if data.get("new_client"):
        if message is not None:
            await answer_msg(
                message, msg_text("coach_selected", profile.language or settings.DEFAULT_LANG).format(name=coach.name)
            )
        await client_request(coach, client, data, bot)
        if message is not None:
            await show_main_menu(cast(Message, message), profile, state)
            await del_msg(cast(Message | CallbackQuery | None, message))
    else:
        if data.get("service_type") == "subscription":
            await state.set_state(States.workout_days)
            if message is not None:
                await answer_msg(
                    message,
                    text=msg_text("select_days", profile.language or settings.DEFAULT_LANG),
                    reply_markup=select_days_kb(profile.language or settings.DEFAULT_LANG, []),
                )
        elif data.get("service_type") == "program":
            required = required_credits(coach.program_price or Decimal("0"))
            if client.credits < required:
                if message is not None:
                    await answer_msg(
                        message,
                        msg_text("not_enough_credits", profile.language or settings.DEFAULT_LANG),
                    )
                    await show_balance_menu(message, profile, state)
                return

            await state.update_data(required=required, coach=coach.model_dump())
            await state.set_state(States.confirm_service)
            if message is not None:
                await answer_msg(
                    message,
                    msg_text("confirm_service", profile.language or settings.DEFAULT_LANG).format(
                        balance=client.credits,
                        price=required,
                    ),
                    reply_markup=yes_no_kb(profile.language or settings.DEFAULT_LANG),
                )
            return
        if message is not None:
            await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.callback_query(States.workout_days)
async def workout_days(callback_query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    lang = profile.language or settings.DEFAULT_LANG

    try:
        client = await Cache.client.get_client(profile.id)
    except ClientNotFoundError:
        logger.error(f"Client profile not found for profile {profile.id}")
        await callback_query.answer(msg_text("unexpected_error", lang))
        return

    days: list[str] = data.get("workout_days", [])

    if callback_query.data != "complete":
        data_val = callback_query.data
        if data_val is not None:
            if data_val in days:
                days.remove(data_val)
            else:
                days.append(data_val)

        await state.update_data(workout_days=days)

        if isinstance(callback_query.message, Message):
            with suppress(TelegramBadRequest):
                await callback_query.message.edit_reply_markup(reply_markup=select_days_kb(lang, days))

        await state.set_state(States.workout_days)
        return

    if not days:
        await callback_query.answer("❌")
        return

    await state.update_data(workout_days=days)
    if data.get("edit_mode"):
        subscription = await Cache.workout.get_latest_subscription(client.id)

        if subscription and len(subscription.workout_days) == len(days):
            await edit_subscription_days(callback_query, days, client.id, state, subscription)
            return

        if isinstance(callback_query.message, Message):
            await answer_msg(
                callback_query.message,
                msg_text("workout_plan_delete_warning", lang),
                reply_markup=yes_no_kb(lang),
            )

        await state.set_state(States.confirm_subscription_reset)
        return

    await callback_query.answer(msg_text("saved", lang))
    await process_new_subscription(callback_query, profile, state)


@questionnaire_router.callback_query(States.profile_delete)
async def delete_profile_confirmation(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])

    if callback_query.data == "yes":
        if profile and profile.role == "coach":
            if await check_assigned_clients(profile.id):
                await answer_msg(
                    cast(Message | CallbackQuery, callback_query),
                    msg_text("unable_to_delete_profile", profile.language or settings.DEFAULT_LANG),
                )
                return

        if profile and await APIService.profile.delete_profile(profile.id):
            await Cache.profile.delete_profile(callback_query.from_user.id)
            await answer_msg(
                cast(Message | CallbackQuery, callback_query),
                msg_text("profile_deleted", profile.language or settings.DEFAULT_LANG),
            )
            await answer_msg(
                cast(Message | CallbackQuery, callback_query),
                msg_text("select_action", profile.language or settings.DEFAULT_LANG),
            )
            await del_msg(cast(Message | CallbackQuery | None, callback_query))
            await state.clear()
        else:
            await answer_msg(
                cast(Message | CallbackQuery, callback_query),
                msg_text("unexpected_error", profile.language or settings.DEFAULT_LANG),
            )
    else:
        if callback_query.message is not None:
            await show_my_profile_menu(cast(CallbackQuery, callback_query), profile, state)


@questionnaire_router.callback_query(States.accept_policy)
async def process_policy(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await callback_query.answer()
    data = await state.get_data()
    role = data.get("role", "client")
    await delete_messages(state)

    if callback_query.data == "yes":
        if callback_query.message is not None:
            await update_profile_data(cast(Message, callback_query.message), state, role, bot)
    else:
        await state.clear()
        if callback_query.message is not None:
            start_msg = await callback_query.message.answer(msg_text("start", settings.DEFAULT_LANG))
            lang_msg = await callback_query.message.answer(
                msg_text("select_language", settings.DEFAULT_LANG),
                reply_markup=select_language_kb(),
            )
            msg_ids = []
            if start_msg:
                msg_ids.append(start_msg.message_id)
            if lang_msg:
                msg_ids.append(lang_msg.message_id)
            await state.update_data(message_ids=msg_ids, chat_id=callback_query.message.chat.id)
            await state.set_state(States.select_language)
        await del_msg(callback_query)
