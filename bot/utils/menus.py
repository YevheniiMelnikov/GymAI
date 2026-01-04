from typing import Any, TypedDict, cast

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, FSInputFile, InlineKeyboardButton as KbBtn, WebAppInfo
from pathlib import Path

from bot import keyboards as kb
from bot.keyboard_builder import SafeInlineKeyboardMarkup as KbMarkup
from bot.keyboards import yes_no_kb, confirm_service_kb
from bot.utils.profiles import fetch_user
from bot.states import States
from bot.texts import ButtonText, MessageText, translate
from core.enums import ProfileStatus
from core.exceptions import ProfileNotFoundError
from core.schemas import Profile
from config.app_settings import settings
from bot.types.messaging import BotMessageProxy
from bot.utils.bot import del_msg, answer_msg, get_webapp_url


async def show_main_menu(message: Message, profile: Profile, state: FSMContext, *, delete_source: bool = True) -> None:
    language = cast(str, profile.language or settings.DEFAULT_LANG)
    webapp_url = get_webapp_url("program", language)
    profile_webapp_url = get_webapp_url("profile", language)
    faq_webapp_url = get_webapp_url("faq", language)
    menu = kb.main_menu_kb(
        language,
        webapp_url=webapp_url,
        profile_webapp_url=profile_webapp_url,
        faq_webapp_url=faq_webapp_url,
    )
    await state.clear()
    await state.update_data(profile=profile.model_dump(mode="json"))
    await state.set_state(States.main_menu)
    await answer_msg(message, translate(MessageText.main_menu, profile.language), reply_markup=menu)
    if delete_source:
        await del_msg(cast(Message | CallbackQuery | None, message))


async def reset_main_menu_state(state: FSMContext, profile: Profile) -> None:
    await state.clear()
    await state.update_data(profile=profile.model_dump(mode="json"))
    await state.set_state(States.main_menu)


InteractionTarget = CallbackQuery | Message | BotMessageProxy


class PendingFlow(TypedDict, total=False):
    name: str
    context: dict[str, Any]


async def show_balance_menu(
    callback_obj: InteractionTarget,
    profile: Profile,
    state: FSMContext,
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
    await state.set_state(States.main_menu)
    await answer_msg(
        callback_obj,
        translate(MessageText.credit_balance_menu, lang).format(credits=cached_profile.credits),
        reply_markup=kb.topup_menu_kb(lang, webapp_url=topup_webapp_url, back_webapp_url=back_webapp_url),
    )
    callback_target = callback_obj if not isinstance(callback_obj, BotMessageProxy) else None
    await del_msg(callback_target)


async def ensure_credits(
    interaction: InteractionTarget,
    profile: Profile,
    state: FSMContext,
    *,
    required: int,
    credits: int | None = None,
) -> bool:
    language = cast(str, profile.language or settings.DEFAULT_LANG)
    available = credits
    if available is None:
        cached_profile = await fetch_user(profile, refresh_if_incomplete=True)
        available = cached_profile.credits
    if available < required:
        message = translate(MessageText.not_enough_credits, language)
        if isinstance(interaction, CallbackQuery):
            await interaction.answer(message, show_alert=True)
            await show_balance_menu(interaction, profile, state, already_answered=True)
        else:
            await answer_msg(interaction, message)
            await show_balance_menu(interaction, profile, state, already_answered=True)
        return False
    return True


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

    webapp_url = get_webapp_url("profile", lang)
    if webapp_url:
        message = cast(Message, callback_query.message)
        assert message
        await callback_query.answer()
        await answer_msg(
            message,
            translate(ButtonText.my_profile, lang),
            reply_markup=KbMarkup(
                inline_keyboard=[
                    [KbBtn(text=translate(ButtonText.my_profile, lang), web_app=WebAppInfo(url=webapp_url))]
                ]
            ),
        )
        await del_msg(cast(Message | CallbackQuery | None, callback_query))
        return

    if isinstance(user, Profile) and user.status != ProfileStatus.completed:
        await prompt_profile_completion_questionnaire(
            callback_query,
            profile,
            state,
            chat_id=callback_query.from_user.id,
            language=lang,
            pending_flow={"name": "show_profile"},
        )
        await del_msg(cast(Message | CallbackQuery | None, callback_query))
        return

    await callback_query.answer(translate(MessageText.unexpected_error, lang), show_alert=True)


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


async def start_diet_flow(
    target: InteractionTarget, profile: Profile, state: FSMContext, *, delete_origin: bool
) -> None:
    language = cast(str, profile.language or settings.DEFAULT_LANG)
    if isinstance(target, CallbackQuery):
        await target.answer()
    try:
        user_profile = await fetch_user(profile, refresh_if_incomplete=True)
    except (ProfileNotFoundError, ValueError):
        await answer_msg(target, translate(MessageText.unexpected_error, language))
        return
    if user_profile.status != ProfileStatus.completed:
        await prompt_profile_completion_questionnaire(
            target,
            profile,
            state,
            pending_flow={"name": "start_diet_flow"},
        )
        if delete_origin:
            await del_msg(target if isinstance(target, (CallbackQuery, Message)) else None)
        return
    if user_profile.diet_products is None:
        await state.update_data(diet_allergies=None, diet_products=[])
        await answer_msg(
            target,
            translate(MessageText.diet_allergies_question, language),
            reply_markup=yes_no_kb(language),
        )
        await state.set_state(States.diet_allergies_choice)
        if delete_origin:
            await del_msg(target if isinstance(target, (CallbackQuery, Message)) else None)
        return
    await state.update_data(
        diet_allergies=user_profile.diet_allergies,
        diet_products=user_profile.diet_products or [],
    )
    required = int(settings.DIET_PLAN_PRICE)
    if user_profile.credits < required:
        if isinstance(target, CallbackQuery):
            await target.answer(translate(MessageText.not_enough_credits, language), show_alert=True)
        await show_balance_menu(target, profile, state, already_answered=True)
        return
    await state.update_data(required=required)
    await state.set_state(States.diet_confirm_service)
    file_path = Path(__file__).resolve().parent.parent / "images" / "ai_diet.png"
    description = translate(MessageText.diet_service_intro, language).format(
        bot_name=settings.BOT_NAME,
        balance=user_profile.credits,
        price=required,
    )
    if file_path.exists():
        await answer_msg(
            target,
            caption=description,
            photo=FSInputFile(file_path),
            reply_markup=confirm_service_kb(language),
        )
    else:
        await answer_msg(
            target,
            description,
            reply_markup=confirm_service_kb(language),
        )
    if delete_origin:
        await del_msg(target if isinstance(target, (CallbackQuery, Message)) else None)
