from contextlib import suppress
from typing import cast

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import diet_confirm_kb, diet_products_kb
from bot.states import States
from bot.texts import MessageText, translate
from bot.utils.bot import answer_msg, del_msg
from bot.utils.diet_plans import (
    DIET_PRODUCT_CALLBACK_PREFIX,
    DIET_PRODUCTS_BACK,
    DIET_PRODUCTS_DONE,
    normalize_diet_products,
    toggle_diet_product,
)
from bot.utils.menus import show_balance_menu, show_main_menu
from bot.utils.ai_coach import enqueue_diet_plan_generation
from bot.utils.profiles import fetch_user, update_diet_preferences, update_profile_data
from config.app_settings import settings
from core.schemas import Profile
from uuid import uuid4

diet_router = Router()


async def _prompt_diet_products(
    origin: CallbackQuery | Message,
    lang: str,
    selected: list[str],
) -> None:
    await answer_msg(
        origin,
        translate(MessageText.diet_products, lang),
        reply_markup=diet_products_kb(lang, set(selected)),
    )


@diet_router.callback_query(States.diet_allergies_choice)
async def diet_allergies_choice(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    lang = profile.language or settings.DEFAULT_LANG
    await callback_query.answer()
    edit_mode = bool(data.get("edit_mode"))

    if (callback_query.data or "").lower() == "yes":
        message = callback_query.message
        if message is not None:
            await answer_msg(
                cast(Message, message),
                translate(MessageText.diet_allergies, lang),
            )
        await state.set_state(States.diet_allergies)
        await del_msg(callback_query)
        return

    await state.update_data(diet_allergies="", diet_products=None if edit_mode else [])
    if edit_mode:
        message = callback_query.message
        if message is not None:
            await update_profile_data(cast(Message, message), state, message.bot)
        await del_msg(callback_query)
        return
    await state.update_data(diet_products=[])
    await state.set_state(States.diet_products)
    await _prompt_diet_products(callback_query, lang, [])
    await del_msg(callback_query)


@diet_router.message(States.diet_allergies)
async def diet_allergies(message: Message, state: FSMContext) -> None:
    if not message.text:
        return
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    lang = profile.language or settings.DEFAULT_LANG
    edit_mode = bool(data.get("edit_mode"))
    await state.update_data(diet_allergies=message.text.strip(), diet_products=None if edit_mode else [])
    if edit_mode:
        await update_profile_data(cast(Message, message), state, message.bot)
        await del_msg(message)
        return
    await state.update_data(diet_products=[])
    await state.set_state(States.diet_products)
    await _prompt_diet_products(message, lang, [])
    await del_msg(message)


@diet_router.callback_query(States.diet_products)
async def diet_products(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    lang = profile.language or settings.DEFAULT_LANG
    payload = callback_query.data or ""
    edit_mode = bool(data.get("edit_mode"))

    if payload == DIET_PRODUCTS_BACK:
        await show_main_menu(cast(Message, callback_query.message), profile, state)
        await del_msg(callback_query)
        return

    if payload == DIET_PRODUCTS_DONE:
        if edit_mode:
            message = callback_query.message
            if message is not None:
                await update_profile_data(cast(Message, message), state, message.bot)
            await del_msg(callback_query)
            return
        try:
            user_profile = await fetch_user(profile)
        except ValueError:
            await answer_msg(callback_query, translate(MessageText.unexpected_error, lang))
            return
        required = int(settings.DIET_PLAN_PRICE)
        if user_profile.credits < required:
            await callback_query.answer(translate(MessageText.not_enough_credits, lang), show_alert=True)
            await show_balance_menu(callback_query, profile, state, already_answered=True)
            return
        updated = await update_diet_preferences(
            profile,
            diet_allergies=str(data.get("diet_allergies") or "").strip(),
            diet_products=normalize_diet_products(data.get("diet_products")),
        )
        if updated is None:
            await answer_msg(callback_query, translate(MessageText.unexpected_error, lang))
            return
        await state.update_data(required=required, profile=updated.model_dump(mode="json"))
        await state.set_state(States.diet_confirm_service)
        await answer_msg(
            callback_query,
            translate(MessageText.confirm_service, lang).format(balance=user_profile.credits, price=required),
            reply_markup=diet_confirm_kb(lang),
        )
        await del_msg(callback_query)
        return

    if not payload.startswith(DIET_PRODUCT_CALLBACK_PREFIX):
        await callback_query.answer()
        return

    product = payload.removeprefix(DIET_PRODUCT_CALLBACK_PREFIX)
    current = normalize_diet_products(data.get("diet_products"))
    updated = toggle_diet_product(current, product)
    await state.update_data(diet_products=updated)
    if callback_query.message is not None:
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_reply_markup(reply_markup=diet_products_kb(lang, set(updated)))
    await callback_query.answer()


@diet_router.callback_query(States.diet_confirm_service)
async def diet_confirm_service(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    lang = profile.language or settings.DEFAULT_LANG
    action = str(callback_query.data or "").lower()
    if action not in {"diet_generate", "diet_back"}:
        await callback_query.answer()
        return
    if action == "diet_back":
        await show_main_menu(cast(Message, callback_query.message), profile, state)
        await del_msg(callback_query)
        return

    required = int(data.get("required", settings.DIET_PLAN_PRICE))
    try:
        user_profile = await fetch_user(profile)
    except ValueError:
        await answer_msg(callback_query, translate(MessageText.unexpected_error, lang))
        return
    if user_profile.credits < required:
        await callback_query.answer(translate(MessageText.not_enough_credits, lang), show_alert=True)
        await show_balance_menu(callback_query, profile, state, already_answered=True)
        return

    data = await state.get_data()
    diet_allergies = str(data.get("diet_allergies") or "").strip() or None
    diet_products = normalize_diet_products(data.get("diet_products"))
    request_id = uuid4().hex
    queued = await enqueue_diet_plan_generation(
        profile=profile,
        diet_allergies=str(diet_allergies).strip() if diet_allergies else None,
        diet_products=diet_products,
        request_id=request_id,
        cost=required,
    )
    if not queued:
        await answer_msg(
            callback_query,
            translate(MessageText.coach_agent_error, lang).format(tg=settings.TG_SUPPORT_CONTACT),
        )
        return
    await answer_msg(callback_query, translate(MessageText.request_in_progress, lang))
    message = callback_query.message
    if message and isinstance(message, Message):
        await show_main_menu(message, profile, state)
    await del_msg(callback_query)
