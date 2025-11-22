from contextlib import suppress
from typing import cast

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
    select_language_kb,
)
from bot.states import States
from config.app_settings import settings
from core.cache import Cache
from core.enums import ProfileStatus, Language
from core.exceptions import ProfileNotFoundError
from core.schemas import Profile
from core.services import APIService
from bot.utils.workout_plans import process_new_subscription, edit_subscription_days
from bot.utils.menus import (
    show_main_menu,
    show_my_profile_menu,
    send_policy_confirmation,
    show_balance_menu,
    show_my_workouts_menu,
)
from bot.utils.profiles import update_profile_data
from bot.utils.text import get_state_and_message
from bot.utils.bot import del_msg, answer_msg, delete_messages, set_bot_commands
from bot.texts.text_manager import msg_text
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
        if callback_query.message is not None:
            question_msg = await answer_msg(
                cast(Message, callback_query.message),
                msg_text("name", lang),
            )
            if question_msg is not None:
                await state.update_data(
                    lang=lang,
                    message_ids=[question_msg.message_id],
                    chat_id=callback_query.message.chat.id,
                )
        await state.set_state(States.name)

    await del_msg(cast(Message | CallbackQuery | None, callback_query))


@questionnaire_router.message(States.name)
async def name(message: Message, state: FSMContext) -> None:
    if not message.text:
        return

    await delete_messages(state)
    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)
    msg = await answer_msg(
        message,
        text=msg_text("choose_gender", lang),
        reply_markup=select_gender_kb(lang),
    )
    await state.update_data(chat_id=message.chat.id, message_ids=[msg.message_id] if msg else [], name=message.text)
    await state.set_state(States.gender)
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
        status=ProfileStatus.initial,
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
        await update_profile_data(cast(Message, message), state, bot)
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
            await update_profile_data(cast(Message, callback_query.message), state, bot)
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
        await update_profile_data(cast(Message, message), state, bot)
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
    await state.update_data(health_notes=message.text, status=ProfileStatus.default)
    if not data.get("edit_mode"):
        await answer_msg(
            message,
            msg_text("initial_credits_granted", data.get("lang", settings.DEFAULT_LANG)),
        )
        await state.update_data(credits_delta=settings.PACKAGE_START_CREDITS)

    await update_profile_data(cast(Message, message), state, bot)


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
    cb_data = callback_query.data or ""

    if cb_data == "workouts_back":
        await show_my_workouts_menu(callback_query, profile, state)
        return

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
        selected_profile = Profile.model_validate(data.get("profile"))
        required = int(data.get("required", 0))
        wishes = message.text
        await state.update_data(wishes=wishes)

        if selected_profile.credits < required:
            await answer_msg(message, msg_text("not_enough_credits", profile.language))
            await show_balance_menu(message, profile, state)
            return

        await state.update_data(wishes=wishes)
        await state.set_state(States.ai_confirm_service)
        await answer_msg(
            message,
            msg_text("confirm_service", profile.language).format(
                balance=selected_profile.credits,
                price=required,
            ),
            reply_markup=yes_no_kb(profile.language),
        )
        if message is not None:
            await del_msg(cast(Message | CallbackQuery | None, message))
        return

    return


@questionnaire_router.callback_query(States.workout_days)
async def workout_days(callback_query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    lang = profile.language or settings.DEFAULT_LANG

    try:
        profile_record = await Cache.profile.get_record(profile.id)
    except ProfileNotFoundError:
        logger.error(f"Profile data not found for profile {profile.id}")
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
        subscription = await Cache.workout.get_latest_subscription(profile_record.id)

        if subscription and len(subscription.workout_days) == len(days):
            await edit_subscription_days(callback_query, days, profile_record.id, state, subscription)
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
    await delete_messages(state)

    if callback_query.data == "yes":
        if callback_query.message is not None:
            await update_profile_data(cast(Message, callback_query.message), state, bot)
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
