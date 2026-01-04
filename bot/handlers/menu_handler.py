from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from typing import cast
from loguru import logger

from bot.states import States
from bot.texts import MessageText, translate
from config.app_settings import settings
from core.cache import Cache
from core.schemas import Profile
from bot.utils.ask_ai import start_ask_ai_prompt
from bot.services.pricing import ServiceCatalog
from bot.utils.menus import (
    show_main_menu,
    show_my_profile_menu,
    prompt_subscription_type,
    start_diet_flow,
    track_prompt_message,
)
from bot.utils.workout_plans import process_new_program, process_new_subscription
from bot.utils.bot import del_msg
from bot.utils.prompts import send_enter_wishes_prompt
from core.services import APIService
from bot.utils.split_number import (
    SPLIT_NUMBER_BACK,
    SPLIT_NUMBER_CONTINUE,
    SPLIT_NUMBER_MINUS,
    SPLIT_NUMBER_PLUS,
    DEFAULT_SPLIT_NUMBER,
    update_split_number_message,
)

menu_router = Router()


@menu_router.callback_query(F.data == "main_menu")
async def main_menu_shortcut(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    profile: Profile | None = None
    if profile_data:
        profile = Profile.model_validate(profile_data)
    else:
        try:
            profile = await Cache.profile.get_profile(callback_query.from_user.id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"main_menu_shortcut_profile_missing tg_id={callback_query.from_user.id} err={exc!s}")
            profile = None
        if profile is None:
            profile = await APIService.profile.get_profile_by_tg_id(callback_query.from_user.id)
            if profile is not None:
                await Cache.profile.save_record(profile.id, profile.model_dump(mode="json"))
    if profile is None:
        await callback_query.answer()
        return
    message = callback_query.message
    if message is None or not isinstance(message, Message):
        await callback_query.answer()
        return
    await callback_query.answer()
    await show_main_menu(message, profile, state)


@menu_router.callback_query(States.main_menu)
async def main_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    message = callback_query.message
    if message is None or not isinstance(message, Message):
        return
    cb_data = callback_query.data or ""

    if cb_data == "back":
        await show_my_profile_menu(callback_query, profile, state)
        return

    if cb_data == "ask_ai":
        await start_ask_ai_prompt(
            callback_query,
            profile,
            state,
            delete_origin=True,
            show_balance_menu_on_insufficient=True,
        )
        return

    elif cb_data == "create_diet":
        await start_diet_flow(callback_query, profile, state, delete_origin=True)
        return

    elif cb_data == "my_profile":
        await show_my_profile_menu(callback_query, profile, state)


@menu_router.callback_query(States.split_number_selection)
async def split_number_selection(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    lang = profile.language or settings.DEFAULT_LANG
    count = int(data.get("split_number", DEFAULT_SPLIT_NUMBER))
    action = callback_query.data
    if action == SPLIT_NUMBER_PLUS:
        if count >= 7:
            await callback_query.answer(translate(MessageText.out_of_range, lang), show_alert=True)
            return
        count += 1
        await state.update_data(split_number=count)
        await update_split_number_message(callback_query, lang, count)
        await callback_query.answer()
        return
    if action == SPLIT_NUMBER_MINUS:
        if count <= 1:
            await callback_query.answer(translate(MessageText.out_of_range, lang), show_alert=True)
            return
        count -= 1
        await state.update_data(split_number=count)
        await update_split_number_message(callback_query, lang, count)
        await callback_query.answer()
        return
    if action == SPLIT_NUMBER_BACK:
        await callback_query.answer()
        await state.set_state(States.enter_wishes)
        prompt = await send_enter_wishes_prompt(callback_query, lang)
        await track_prompt_message(state, prompt)
        await del_msg(callback_query)
        return
    if action != SPLIT_NUMBER_CONTINUE:
        await callback_query.answer()
        return
    await callback_query.answer()
    service = data.get("split_number_service", "program")
    await state.update_data(split_number=count)
    await del_msg(callback_query)
    if service == "program":
        await process_new_program(callback_query, profile, state, confirmed=False)
        return
    if service == "subscription":
        await prompt_subscription_type(callback_query, profile, state)
        return
    await process_new_subscription(callback_query, profile, state, confirmed=False)
    return


@menu_router.callback_query(States.choose_subscription)
async def subscription_choice(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    cb_data = callback_query.data or ""

    if cb_data == "back":
        message = callback_query.message
        if message is not None:
            await show_main_menu(cast(Message, message), profile, state, delete_source=False)
        return

    if not cb_data.startswith("subscription_type_"):
        await callback_query.answer()
        return

    service_name = cb_data.removeprefix("subscription_type_")
    services = {service.name: service.credits for service in ServiceCatalog.ai_services()}
    required = services.get(service_name)
    if required is None:
        await callback_query.answer(translate(MessageText.unexpected_error, profile.language), show_alert=True)
        return

    await state.update_data(ai_service=service_name, required=required)
    await del_msg(callback_query)
    await process_new_subscription(callback_query, profile, state, confirmed=False)
