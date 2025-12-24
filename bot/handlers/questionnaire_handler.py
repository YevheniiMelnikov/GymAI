from typing import cast

from aiogram import Router, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from bot.keyboards import (
    select_gender_kb,
    workout_experience_kb,
    workout_location_kb,
    yes_no_kb,
    select_language_kb,
    diet_products_kb,
)
from bot.states import States
from config.app_settings import settings
from core.cache import Cache
from core.enums import ProfileStatus, Language
from core.exceptions import ProfileNotFoundError
from core.schemas import Profile
from core.services import APIService
from bot.utils.menus import (
    show_main_menu,
    show_my_profile_menu,
    send_policy_confirmation,
    show_balance_menu,
)
from bot.utils.profiles import resolve_workout_location, should_grant_gift_credits, update_profile_data
from bot.utils.diet_plans import normalize_diet_products
from bot.utils.workout_days import service_period_value, start_workout_days_selection
from bot.utils.text import get_state_and_message
from bot.utils.bot import del_msg, answer_msg, delete_messages, set_bot_commands
from bot.utils.other import parse_int_with_decimal
from bot.texts import MessageText, translate
from core.utils.validators import extract_birth_year

questionnaire_router = Router()
HEALTH_NOTES_PLACEHOLDER = "-"


@questionnaire_router.callback_query(States.select_language)
async def select_language(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await callback_query.answer()
    await delete_messages(state)
    selected_lang = callback_query.data or settings.DEFAULT_LANG
    try:
        language = Language(selected_lang)
    except ValueError:
        logger.warning("Unsupported language code %s in select_language handler", selected_lang)
        language = Language(settings.DEFAULT_LANG)
    lang = language.value
    await state.update_data(lang=lang)
    await set_bot_commands(bot, lang)
    try:
        profile = await APIService.profile.get_profile_by_tg_id(callback_query.from_user.id)
        if profile and profile.status != ProfileStatus.deleted:
            await APIService.profile.update_profile(profile.id, {"language": lang})
            await Cache.profile.update_profile(callback_query.from_user.id, dict(language=lang))
            profile.language = language
            message = callback_query.message
            if message is not None:
                await show_main_menu(cast(Message, message), profile, state)
        else:
            raise ProfileNotFoundError(callback_query.from_user.id)
    except ProfileNotFoundError:
        if callback_query.message is not None:
            prompt = await answer_msg(
                cast(Message, callback_query.message),
                translate(MessageText.choose_gender, lang),
                reply_markup=select_gender_kb(lang),
            )
            if prompt is not None:
                await state.update_data(
                    message_ids=[prompt.message_id],
                    chat_id=callback_query.message.chat.id,
                )
        await state.set_state(States.gender)

    await del_msg(cast(Message | CallbackQuery | None, callback_query))


@questionnaire_router.callback_query(States.gender)
async def gender(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)
    await callback_query.answer(translate(MessageText.saved, lang))
    msg = None
    if callback_query.message is not None:
        msg = await answer_msg(cast(Message, callback_query.message), translate(MessageText.born_in, lang))
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
    year = extract_birth_year(message.text)
    if year is None:
        await answer_msg(message, translate(MessageText.invalid_content, lang))
        return

    await state.update_data(
        born_in=str(year),
        chat_id=message.chat.id,
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
        translate(MessageText.workout_location, lang),
        reply_markup=workout_location_kb(lang),
    )
    await state.update_data(chat_id=message.chat.id, message_ids=[msg.message_id] if msg else [])
    await state.set_state(States.workout_location)
    await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.callback_query(States.workout_location)
async def workout_location(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await delete_messages(state)
    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)
    await callback_query.answer(translate(MessageText.saved, lang))
    await state.update_data(workout_location=callback_query.data)
    if data.get("edit_mode"):
        if callback_query.message is not None:
            await update_profile_data(cast(Message, callback_query.message), state, bot)
        return

    if callback_query.message is not None:
        msg = await answer_msg(
            cast(Message, callback_query.message),
            translate(MessageText.workout_experience, lang),
            reply_markup=workout_experience_kb(lang),
        )
        await state.update_data(
            chat_id=callback_query.message.chat.id,
            message_ids=[msg.message_id] if msg else [],
        )
    await state.set_state(States.workout_experience)
    await del_msg(cast(Message | CallbackQuery | None, callback_query))


@questionnaire_router.callback_query(States.workout_experience)
async def workout_experience(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await delete_messages(state)
    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)
    await callback_query.answer(translate(MessageText.saved, lang))
    await state.update_data(workout_experience=callback_query.data)
    if data.get("edit_mode"):
        if callback_query.message is not None:
            await update_profile_data(cast(Message, callback_query.message), state, bot)
        return

    if callback_query.message is not None:
        msg = await answer_msg(cast(Message, callback_query.message), translate(MessageText.weight, lang))
        await state.update_data(chat_id=callback_query.message.chat.id, message_ids=[msg.message_id] if msg else [])
    await state.set_state(States.weight)
    await del_msg(cast(Message | CallbackQuery | None, callback_query))


@questionnaire_router.message(States.weight)
async def weight(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)
    await delete_messages(state)

    if not message.text:
        await answer_msg(message, translate(MessageText.invalid_content, lang))
        await state.set_state(States.weight)
        return
    try:
        weight_value = parse_int_with_decimal(message.text)
    except ValueError:
        await answer_msg(message, translate(MessageText.invalid_content, lang))
        await state.set_state(States.weight)
        return

    await state.update_data(weight=weight_value)
    if data.get("edit_mode"):
        await update_profile_data(cast(Message, message), state, bot)
        return

    prompt = await answer_msg(message, translate(MessageText.height, lang))
    await state.update_data(chat_id=message.chat.id, message_ids=[prompt.message_id] if prompt else [])
    await state.set_state(States.height)
    await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.message(States.height)
async def height(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)
    await delete_messages(state)

    if not message.text:
        await answer_msg(message, translate(MessageText.invalid_content, lang))
        await state.set_state(States.height)
        return
    try:
        height_value = parse_int_with_decimal(message.text)
    except ValueError:
        await answer_msg(message, translate(MessageText.invalid_content, lang))
        await state.set_state(States.height)
        return

    await state.update_data(height=height_value)
    if data.get("edit_mode"):
        await update_profile_data(cast(Message, message), state, bot)
        return

    prompt = await answer_msg(
        message,
        translate(MessageText.health_notes_question, lang),
        reply_markup=yes_no_kb(lang),
    )
    await state.update_data(chat_id=message.chat.id, message_ids=[prompt.message_id] if prompt else [])
    await state.set_state(States.health_notes_choice)
    await del_msg(cast(Message | CallbackQuery | None, message))


@questionnaire_router.callback_query(States.health_notes_choice)
async def health_notes_choice(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)
    await callback_query.answer()
    await delete_messages(state)

    if (callback_query.data or "").lower() == "yes":
        message = callback_query.message
        if message is not None:
            prompt = await answer_msg(
                cast(Message, message),
                translate(MessageText.health_notes, lang),
            )
            await state.update_data(
                chat_id=message.chat.id,
                message_ids=[prompt.message_id] if prompt else [],
            )
        await state.set_state(States.health_notes)
        await del_msg(cast(Message | CallbackQuery | None, callback_query))
        return

    await state.update_data(health_notes=HEALTH_NOTES_PLACEHOLDER, status=ProfileStatus.completed)
    if not data.get("edit_mode"):
        if await should_grant_gift_credits(callback_query.from_user.id):
            credits_text = translate(MessageText.initial_credits_granted, lang).format(credits=settings.DEFAULT_CREDITS)
            await answer_msg(callback_query, credits_text)
            await state.update_data(credits_delta=settings.DEFAULT_CREDITS)

    if callback_query.message is not None:
        await update_profile_data(cast(Message, callback_query.message), state, bot)
    await del_msg(cast(Message | CallbackQuery | None, callback_query))


@questionnaire_router.message(States.health_notes)
async def health_notes(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.text:
        return

    await delete_messages(state)
    data = await state.get_data()
    await state.update_data(health_notes=message.text, status=ProfileStatus.completed)
    if not data.get("edit_mode"):
        if await should_grant_gift_credits(message.from_user.id):
            credits_text = translate(
                MessageText.initial_credits_granted,
                data.get("lang", settings.DEFAULT_LANG),
            ).format(credits=settings.DEFAULT_CREDITS)
            await answer_msg(message, credits_text)
            await state.update_data(credits_delta=settings.DEFAULT_CREDITS)

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
    reply_markup = None
    if state_to_set == States.workout_experience:
        reply_markup = workout_experience_kb(profile.language or settings.DEFAULT_LANG)
    elif state_to_set == States.workout_location:
        reply_markup = workout_location_kb(profile.language or settings.DEFAULT_LANG)
    elif state_to_set == States.health_notes_choice:
        reply_markup = yes_no_kb(profile.language or settings.DEFAULT_LANG)
    elif state_to_set == States.diet_allergies_choice:
        reply_markup = yes_no_kb(profile.language or settings.DEFAULT_LANG)
    if callback_query.message is not None:
        if state_to_set == States.diet_products:
            selected = normalize_diet_products(profile.diet_products)
            await state.update_data(diet_products=selected)
            await answer_msg(
                cast(Message, callback_query.message),
                message_text,
                reply_markup=diet_products_kb(profile.language or settings.DEFAULT_LANG, set(selected)),
            )
        else:
            await answer_msg(cast(Message, callback_query.message), message_text, reply_markup=reply_markup)
    await state.set_state(state_to_set)
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
            await answer_msg(message, translate(MessageText.not_enough_credits, profile.language))
            await show_balance_menu(message, profile, state)
            return

        service = str(data.get("ai_service") or "program")
        lang = profile.language or settings.DEFAULT_LANG

        if service == "program":
            workout_location = resolve_workout_location(selected_profile)
            if workout_location is None:
                logger.error(f"Workout location missing for completed profile_id={selected_profile.id}")
                await answer_msg(message, translate(MessageText.unexpected_error, lang))
                return
            await start_workout_days_selection(
                message,
                state,
                lang=lang,
                service=service,
                workout_location=workout_location.value,
                show_wishes_prompt=False,
            )
            return

        period_value = service_period_value(service)
        await start_workout_days_selection(
            message,
            state,
            lang=lang,
            service=service,
            period_value=period_value,
            show_wishes_prompt=False,
        )
        return

    return


@questionnaire_router.callback_query(States.profile_delete)
async def delete_profile_confirmation(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])

    if callback_query.data == "yes":
        if profile and await APIService.profile.delete_profile(profile.id):
            await Cache.profile.delete_record(profile.id)
            await answer_msg(
                cast(Message | CallbackQuery, callback_query),
                translate(MessageText.profile_deleted, profile.language or settings.DEFAULT_LANG),
            )
            await del_msg(cast(Message | CallbackQuery | None, callback_query))
            await state.clear()
        else:
            await answer_msg(
                cast(Message | CallbackQuery, callback_query),
                translate(MessageText.unexpected_error, profile.language or settings.DEFAULT_LANG),
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
            await state.update_data(status=ProfileStatus.created)
            await update_profile_data(cast(Message, callback_query.message), state, bot)
    else:
        await state.clear()
        if callback_query.message is not None:
            start_msg = await callback_query.message.answer(translate(MessageText.start, settings.DEFAULT_LANG))
            lang_msg = await callback_query.message.answer(
                translate(MessageText.select_language, settings.DEFAULT_LANG),
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
