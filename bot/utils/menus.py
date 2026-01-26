from typing import Any, cast

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot import keyboards as kb
from bot.utils.profiles import fetch_user
from bot.states import States
from bot.texts import MessageText, translate
from core.schemas import Profile
from config.app_settings import settings
from bot.types.messaging import BotMessageProxy
from bot.utils.bot import del_msg, answer_msg
from bot.utils.urls import get_webapp_url


InteractionTarget = CallbackQuery | Message | BotMessageProxy


async def send_main_menu_to_chat(bot: Bot, chat_id: int, profile: Profile, state: FSMContext) -> None:
    language = cast(str, profile.language or settings.DEFAULT_LANG)
    webapp_url = get_webapp_url("program", language)
    diet_webapp_url = get_webapp_url("diets", language)
    profile_webapp_url = get_webapp_url("profile", language)
    faq_webapp_url = get_webapp_url("faq", language)
    menu = kb.main_menu_kb(
        language,
        webapp_url=webapp_url,
        diet_webapp_url=diet_webapp_url,
        profile_webapp_url=profile_webapp_url,
        faq_webapp_url=faq_webapp_url,
    )
    await state.clear()
    await state.update_data(profile=profile.model_dump(mode="json"))
    await bot.send_message(chat_id, translate(MessageText.main_menu, language), reply_markup=menu)


async def show_main_menu(message: Message, profile: Profile, state: FSMContext, *, delete_source: bool = True) -> None:
    if message.bot:
        await send_main_menu_to_chat(message.bot, message.chat.id, profile, state)
    if delete_source:
        await del_msg(cast(Message | CallbackQuery | None, message))


async def show_balance_menu(
    callback_obj: InteractionTarget,
    profile: Profile,
    *,
    already_answered: bool = False,
    back_webapp_url: str | None = None,
) -> None:
    lang = cast(str, profile.language)
    if back_webapp_url is None:
        back_webapp_url = get_webapp_url("profile", lang)
    cached_profile = await fetch_user(profile, refresh_if_incomplete=True)
    topup_webapp_url = get_webapp_url("topup", lang)
    if isinstance(callback_obj, CallbackQuery) and not already_answered:
        await callback_obj.answer()
    await answer_msg(
        callback_obj,
        translate(MessageText.credit_balance_menu, lang).format(credits=cached_profile.credits),
        reply_markup=kb.topup_menu_kb(lang, webapp_url=topup_webapp_url, back_webapp_url=back_webapp_url),
    )
    callback_target = callback_obj if not isinstance(callback_obj, BotMessageProxy) else None
    await del_msg(callback_target)


def _extract_chat_id(target: InteractionTarget) -> int | None:
    if isinstance(target, CallbackQuery):
        user = target.from_user
        if user:
            return user.id
    elif isinstance(target, Message):
        return target.chat.id
    elif isinstance(target, BotMessageProxy):
        return target.chat_id
    return None


async def _start_profile_questionnaire(
    target: InteractionTarget,
    profile: Profile,
    state: FSMContext,
    *,
    language: str | None = None,
    chat_id: int | None = None,
    pending_flow: dict[str, object] | None = None,
) -> None:
    lang = language or cast(str, profile.language or settings.DEFAULT_LANG)
    msg = await answer_msg(target, translate(MessageText.workout_goals, lang))
    message_ids: list[int] = [msg.message_id] if msg else []
    data: dict[str, Any] = {"lang": lang, "message_ids": message_ids}
    if pending_flow:
        data["pending_flow"] = pending_flow
    resolved_chat_id = chat_id or _extract_chat_id(target)
    if resolved_chat_id is not None:
        data["chat_id"] = resolved_chat_id
    await state.update_data(**data)
    await state.set_state(States.workout_goals)


async def prompt_profile_completion_questionnaire(
    target: InteractionTarget,
    profile: Profile,
    state: FSMContext,
    *,
    chat_id: int | None = None,
    language: str | None = None,
    pending_flow: dict[str, object] | None = None,
) -> None:
    lang = language or cast(str, profile.language or settings.DEFAULT_LANG)
    text = translate(MessageText.finish_registration, lang)
    if isinstance(target, CallbackQuery):
        await target.answer(text, show_alert=True)
    else:
        await answer_msg(target, text)
    await _start_profile_questionnaire(
        target,
        profile,
        state,
        language=lang,
        chat_id=chat_id,
        pending_flow=pending_flow,
    )
