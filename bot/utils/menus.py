from contextlib import suppress
from typing import Collection, cast

from loguru import logger
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, FSInputFile
from pathlib import Path

from bot import keyboards as kb
from bot.keyboards import subscription_manage_kb, program_edit_kb, program_view_kb, select_gender_kb
from bot.utils.profiles import fetch_user, answer_profile
from bot.utils.credits import available_packages, available_ai_services
from bot.states import States
from bot.texts import MessageText, translate
from core.cache import Cache
from core.enums import ProfileStatus
from core.exceptions import ProfileNotFoundError
from core.schemas import Profile, Subscription
from bot.utils.text import (
    get_profile_attributes,
    get_translated_week_day,
)
from bot.utils.exercises import format_full_program
from config.app_settings import settings
from bot.utils.bot import del_msg, answer_msg, get_webapp_url


async def show_subscription_page(callback_query: CallbackQuery, state: FSMContext, subscription: Subscription) -> None:
    await callback_query.answer()
    profile = await Cache.profile.get_profile(callback_query.from_user.id)
    assert profile is not None
    lang = cast(str, profile.language)

    next_payment_date_str = subscription.payment_date
    enabled_status = "✅" if subscription.enabled else "❌"
    translated_week_days = ", ".join(get_translated_week_day(lang, x) for x in subscription.workout_days)

    await state.set_state(States.show_subscription)
    message = callback_query.message

    if message and isinstance(message, Message):
        await answer_msg(
            message,
            translate(MessageText.subscription_page, lang).format(
                next_payment_date=next_payment_date_str,
                enabled=enabled_status,
                price=subscription.price,
                days=translated_week_days,
            ),
            reply_markup=kb.show_subscriptions_kb(lang, get_webapp_url("subscription", lang)),
        )
        await del_msg(message)


async def show_profile_editing_menu(message: Message, profile: Profile, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(lang=profile.language)

    user_profile: Profile | None = None
    reply_markup = None
    try:
        user_profile = await Cache.profile.get_record(profile.id)
        reply_markup = kb.edit_profile_kb(profile.language)
    except ProfileNotFoundError:
        logger.info(f"Profile data not found for profile {profile.id} during profile editing setup.")

    state_to_set = States.edit_profile if user_profile else States.gender
    response_text = MessageText.choose_profile_parameter if user_profile else MessageText.edit_profile

    profile_msg = await answer_msg(
        message,
        translate(response_text, profile.language),
        reply_markup=reply_markup,
    )
    if profile_msg is None:
        logger.error("Failed to send profile editing menu message")
        return

    with suppress(TelegramBadRequest):
        await del_msg(cast(Message | CallbackQuery | None, message))

    message_ids = [profile_msg.message_id]
    if not user_profile:
        gender_msg = await answer_msg(
            message,
            translate(MessageText.choose_gender, profile.language),
            reply_markup=select_gender_kb(profile.language),
        )
        if gender_msg is not None:
            message_ids.append(gender_msg.message_id)

    await state.update_data(message_ids=message_ids, chat_id=message.chat.id)
    await state.set_state(state_to_set)


async def show_main_menu(message: Message, profile: Profile, state: FSMContext, *, delete_source: bool = True) -> None:
    menu = kb.main_menu_kb
    await state.clear()
    await state.update_data(profile=profile.model_dump())
    await state.set_state(States.main_menu)
    await answer_msg(message, translate(MessageText.main_menu, profile.language), reply_markup=menu(profile.language))
    if delete_source:
        await del_msg(cast(Message | CallbackQuery | None, message))


async def show_balance_menu(
    callback_obj: CallbackQuery | Message,
    profile: Profile,
    state: FSMContext,
    *,
    already_answered: bool = False,
) -> None:
    lang = cast(str, profile.language)
    cached_profile = await Cache.profile.get_record(profile.id)
    plans = [p.name for p in available_packages()]
    file_path = Path(settings.BOT_PAYMENT_OPTIONS) / f"credit_packages_{lang}.png"
    packages_img = FSInputFile(file_path)
    if isinstance(callback_obj, CallbackQuery) and not already_answered:
        await callback_obj.answer()
    await state.set_state(States.choose_plan)
    await answer_msg(
        callback_obj,
        caption=(
            translate(MessageText.credit_balance, lang).format(credits=cached_profile.credits)
            + "\n"
            + translate(MessageText.tariff_plans, lang)
        ),
        photo=packages_img,
        reply_markup=kb.tariff_plans_kb(lang, plans),
    )
    await del_msg(callback_obj)


async def show_tariff_plans(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    language = cast(str, profile.language)
    plans = [p.name for p in available_packages()]
    await callback_query.answer()
    await state.set_state(States.choose_plan)
    file_path = Path(settings.BOT_PAYMENT_OPTIONS) / f"credit_packages_{language}.png"
    packages_img = FSInputFile(file_path)
    await answer_msg(
        callback_query,
        caption=translate(MessageText.tariff_plans, language),
        photo=packages_img,
        reply_markup=kb.tariff_plans_kb(language, plans),
    )
    await del_msg(callback_query)


async def send_policy_confirmation(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = data.get("lang", settings.DEFAULT_LANG)

    info_msg = await answer_msg(
        message,
        translate(MessageText.contract_info_message, lang).format(
            public_offer=settings.PUBLIC_OFFER,
            privacy_policy=settings.PRIVACY_POLICY,
        ),
        disable_web_page_preview=True,
    )
    confirm_msg = await answer_msg(
        message,
        translate(MessageText.accept_policy, lang),
        reply_markup=kb.yes_no_kb(lang),
    )
    message_ids: list[int] = []
    if info_msg:
        message_ids.append(info_msg.message_id)
    if confirm_msg:
        message_ids.append(confirm_msg.message_id)
    await state.update_data(chat_id=message.chat.id, message_ids=message_ids)
    await del_msg(message)


async def show_my_profile_menu(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    user = await fetch_user(profile, refresh_if_incomplete=True)
    lang = cast(str, profile.language)

    if isinstance(user, Profile) and user.status != ProfileStatus.completed:
        credits_text = translate(MessageText.finish_registration_to_get_credits, lang).format(
            credits=settings.DEFAULT_CREDITS
        )
        await callback_query.answer(credits_text, show_alert=True)
        await state.set_state(States.workout_goals)
        msg = await answer_msg(callback_query, translate(MessageText.workout_goals, lang))
        if msg is not None:
            await state.update_data(
                chat_id=callback_query.from_user.id,
                message_ids=[msg.message_id],
                lang=lang,
            )
        await del_msg(cast(Message | CallbackQuery | None, callback_query))
        return

    text = translate(MessageText.profile_info, lang).format(**get_profile_attributes(user, lang))

    await answer_profile(
        callback_query,
        profile,
        user,
        text,
        show_balance=True,
    )
    await state.set_state(States.profile)
    await del_msg(cast(Message | CallbackQuery | None, callback_query))


async def show_my_workouts_menu(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    lang = cast(str, profile.language)

    try:
        cached_profile = await fetch_user(profile, refresh_if_incomplete=True)
    except ProfileNotFoundError:
        logger.error(f"Profile data not found for profile {profile.id} in show_my_workouts_menu.")
        await callback_query.answer(translate(MessageText.questionnaire_not_completed, lang), show_alert=True)
        message = cast(Message, callback_query.message)
        assert message
        await show_profile_editing_menu(message, profile, state)
        return

    message = cast(Message, callback_query.message)
    assert message

    if cached_profile.status != ProfileStatus.completed:
        credits_text = translate(MessageText.finish_registration_to_get_credits, lang).format(
            credits=settings.DEFAULT_CREDITS
        )
        await callback_query.answer(credits_text, show_alert=True)
        await state.set_state(States.workout_goals)
        msg = await answer_msg(callback_query, translate(MessageText.workout_goals, lang))
        if msg is not None:
            await state.update_data(
                chat_id=callback_query.from_user.id,
                message_ids=[msg.message_id],
                lang=lang,
            )
        return

    await state.set_state(States.select_service)
    await answer_msg(
        message,
        translate(MessageText.select_service, lang),
        reply_markup=kb.select_service_kb(lang),
    )

    await del_msg(cast(Message | CallbackQuery | None, message))


async def show_my_subscription_menu(
    callback_query: CallbackQuery,
    profile: Profile,
    state: FSMContext,
    *,
    force_new: bool = False,
) -> None:
    language = cast(str, profile.language)
    message = cast(Message, callback_query.message)
    assert message

    webapp_url = get_webapp_url("subscription", language)

    await callback_query.answer()
    await state.set_state(States.subscription_action_choice)
    await answer_msg(
        message,
        translate(MessageText.select_action, language),
        reply_markup=kb.subscription_action_kb(language, webapp_url),
    )
    await del_msg(cast(Message | CallbackQuery | None, message))


async def show_my_program_menu(callback_query: CallbackQuery, profile: Profile, state: FSMContext) -> None:
    message = cast(Message, callback_query.message)
    assert message
    await answer_msg(
        message,
        translate(MessageText.select_action, profile.language),
        reply_markup=kb.program_action_kb(profile.language, get_webapp_url("program", profile.language)),
    )
    await state.set_state(States.program_action_choice)
    await del_msg(cast(Message | CallbackQuery | None, message))


async def show_ai_services(
    callback_query: CallbackQuery,
    profile: Profile,
    state: FSMContext,
    allowed_services: Collection[str] | None = None,
    *,
    auto_select_single: bool = False,
) -> None:
    language = cast(str, profile.language or settings.DEFAULT_LANG)
    cached_profile = await fetch_user(profile, refresh_if_incomplete=True)
    if cached_profile.status != ProfileStatus.completed:
        credits_text = translate(MessageText.finish_registration_to_get_credits, language).format(
            credits=settings.DEFAULT_CREDITS
        )
        await callback_query.answer(credits_text, show_alert=True)
    else:
        await callback_query.answer()
    file_path = Path(__file__).resolve().parent.parent / "images" / "ai_coach.png"
    services = available_ai_services()
    if allowed_services is not None:
        allowed_set = {name for name in allowed_services}
        filtered_services = [service for service in services if service.name in allowed_set]
        if filtered_services:
            services = filtered_services
    if auto_select_single and len(services) == 1:
        handled = await process_ai_service_selection(
            callback_query,
            profile,
            state,
            service_name=services[0].name,
        )
        if handled:
            await del_msg(callback_query)
        return
    await state.set_state(States.choose_ai_service)
    await answer_msg(
        callback_query,
        caption=translate(MessageText.ai_services, language).format(
            balance=cached_profile.credits,
            bot_name=settings.BOT_NAME,
        ),
        photo=FSInputFile(file_path),
        reply_markup=kb.ai_services_kb(language, [p.name for p in services]),
    )
    await del_msg(callback_query)


async def process_ai_service_selection(
    callback_query: CallbackQuery,
    profile: Profile,
    state: FSMContext,
    *,
    service_name: str,
) -> bool:
    language = cast(str, profile.language or settings.DEFAULT_LANG)
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        await callback_query.answer(translate(MessageText.unexpected_error, language), show_alert=True)
        return False

    selected_profile = Profile.model_validate(profile_data)
    services = {service.name: service.credits for service in available_ai_services()}
    required = services.get(service_name)
    if required is None:
        await callback_query.answer(translate(MessageText.unexpected_error, language), show_alert=True)
        return False

    if selected_profile.credits < required:
        await callback_query.answer(translate(MessageText.not_enough_credits, language), show_alert=True)
        await show_balance_menu(callback_query, profile, state, already_answered=True)
        return False

    await state.update_data(
        ai_service=service_name,
        required=required,
    )
    await state.set_state(States.enter_wishes)
    await answer_msg(callback_query, translate(MessageText.enter_wishes, language))
    return True


async def show_exercises_menu(callback_query: CallbackQuery, state: FSMContext, profile: Profile) -> None:
    message = cast(Message, callback_query.message)
    assert message
    language = cast(str, profile.language)

    webapp_url = get_webapp_url("program", language)
    if webapp_url is None:
        logger.warning(f"program_view_missing_webapp_url profile_id={profile.id} language={language}")
        reply_markup = None
    else:
        reply_markup = program_view_kb(language, webapp_url)

    await answer_msg(
        message,
        translate(MessageText.new_workout_plan, language),
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )

    await state.update_data(profile_view=True, day_index=0)
    await state.set_state(States.program_view)
    await del_msg(cast(Message | CallbackQuery | None, message))


async def program_menu_pagination(state: FSMContext, callback_query: CallbackQuery) -> None:
    profile = await Cache.profile.get_profile(callback_query.from_user.id)
    assert profile is not None

    if callback_query.data == "quit":
        await callback_query.answer()
        message = callback_query.message
        if message and isinstance(message, Message):
            await show_main_menu(message, profile, state)
        return

    data = await state.get_data()
    current_day = data.get("day_index", 0)

    split_number = data.get("split")
    assert split_number is not None

    if data.get("profile_view"):
        webapp_url = get_webapp_url("program", profile.language)
        if webapp_url is None:
            logger.warning(f"program_pagination_missing_webapp_url profile_id={profile.id} language={profile.language}")
            reply_markup = None
        else:
            reply_markup = program_view_kb(profile.language, webapp_url)
        state_to_set = States.program_view
    else:
        reply_markup = (
            subscription_manage_kb(profile.language) if data.get("subscription") else program_edit_kb(profile.language)
        )
        state_to_set = States.subscription_manage if data.get("subscription") else States.program_edit

    await state.set_state(state_to_set)
    current_day += -1 if callback_query.data in ["prev_day", "previous"] else 1

    if current_day < 0 or current_day >= split_number:
        current_day = max(0, min(current_day, split_number - 1))
        await callback_query.answer(translate(MessageText.out_of_range, profile.language))
        await state.update_data(day_index=current_day)
        return

    await state.update_data(day_index=current_day)

    with suppress(TelegramBadRequest):
        message = callback_query.message
        if message and isinstance(message, Message):
            await message.edit_text(
                translate(MessageText.new_workout_plan, profile.language),
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )

    await callback_query.answer()


async def show_subscription_history(
    callback_query: CallbackQuery,
    profile: Profile,
    state: FSMContext,
    index: int = 0,
) -> None:
    subscriptions = await Cache.workout.get_all_subscriptions(profile.id)
    if not subscriptions:
        await callback_query.answer(translate(MessageText.subscription_canceled, profile.language), show_alert=True)
        return

    index %= len(subscriptions)
    sub = subscriptions[index]
    program_text = await format_full_program(sub.exercises)
    date = sub.payment_date

    await state.update_data(subscriptions_history=[s.model_dump() for s in subscriptions])
    await state.set_state(States.subscription_history)

    message = callback_query.message
    if message and isinstance(message, Message):
        await message.edit_text(
            translate(MessageText.subscription_history_page, profile.language).format(program=program_text, date=date),
            reply_markup=kb.history_nav_kb(profile.language, "sh", index),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


async def subscription_history_pagination(
    callback_query: CallbackQuery,
    profile: Profile,
    index: int,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    subs_data = data.get("subscriptions_history", [])
    subscriptions = [Subscription.model_validate(s) for s in subs_data]

    if not subscriptions:
        await callback_query.answer(translate(MessageText.subscription_canceled, profile.language))
        return

    if index < 0 or index >= len(subscriptions):
        await callback_query.answer(translate(MessageText.out_of_range, profile.language))
        return

    sub = subscriptions[index]
    program_text = await format_full_program(sub.exercises)
    date = sub.payment_date
    message = callback_query.message
    if message and isinstance(message, Message):
        await message.edit_text(
            translate(MessageText.subscription_history_page, profile.language).format(program=program_text, date=date),
            reply_markup=kb.history_nav_kb(profile.language, "sh", index),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    await callback_query.answer()
