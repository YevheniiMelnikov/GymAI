from contextlib import suppress
from uuid import uuid4

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from loguru import logger

from bot.states import States
from bot.texts import translate, MessageText
from bot.utils.ai_coach.ask_ai import start_ask_ai_prompt, prepare_ask_ai_request, enqueue_ai_question
from bot.utils.urls import support_contact_url
from config.app_settings import settings
from core.exceptions import AskAiPreparationError
from core.schemas import Profile
from bot.utils.menus import show_main_menu
from bot.utils.bot import del_msg, answer_msg, notify_request_in_progress

chat_router = Router()


@chat_router.callback_query(F.data == "quit")
async def dismiss_message(callback_query: CallbackQuery) -> None:
    if callback_query.message:
        await callback_query.message.delete()
    await callback_query.answer()


@chat_router.callback_query(F.data == "ask_ai")
async def ask_ai_handler(callback_query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        return
    profile = Profile.model_validate(profile_data)
    message = callback_query.message
    if message is None or not isinstance(message, Message):
        return

    await start_ask_ai_prompt(
        callback_query,
        profile,
        state,
        delete_origin=True,
        show_balance_menu_on_insufficient=True,
    )


@chat_router.callback_query(States.ask_ai_question)
async def ask_ai_question_navigation(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        await callback_query.answer()
        await del_msg(callback_query)
        return
    profile = Profile.model_validate(profile_data)
    if callback_query.data != "ask_ai_back":
        await callback_query.answer()
        return

    await callback_query.answer()
    await state.update_data(ask_ai_prompt_id=None, ask_ai_prompt_chat_id=None, ask_ai_cost=None)
    await del_msg(callback_query)
    if callback_query.message and isinstance(callback_query.message, Message):
        await show_main_menu(callback_query.message, profile, state)


@chat_router.message(States.ask_ai_question)
async def process_ask_ai_question(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    profile_data = data.get("profile")
    if not profile_data:
        await answer_msg(message, translate(MessageText.unexpected_error, settings.DEFAULT_LANG))
        await del_msg(message)
        return

    profile = Profile.model_validate(profile_data)
    lang = profile.language or settings.DEFAULT_LANG

    try:
        ask_ai_prompt_id = data.get("ask_ai_prompt_id")
        ask_ai_prompt_chat_id = data.get("ask_ai_prompt_chat_id")
        if ask_ai_prompt_id:
            chat_id = int(ask_ai_prompt_chat_id or message.chat.id)
            with suppress(TelegramBadRequest):
                await bot.delete_message(chat_id, int(ask_ai_prompt_id))
            await state.update_data(ask_ai_prompt_id=None, ask_ai_prompt_chat_id=None)

        try:
            preparation = await prepare_ask_ai_request(
                message=message,
                profile=profile,
                state_data=data,
                bot=bot,
            )
        except AskAiPreparationError as error:
            try:
                message_key = MessageText[error.message_key]
            except KeyError as exc:
                raise ValueError(f"Unknown message key {error.message_key}") from exc
            response = translate(message_key, lang)
            if error.params:
                response = response.format(**error.params)
            await answer_msg(message, response)
            if error.delete_message:
                await del_msg(message)
            return

        user_profile = preparation.profile
        question_text = preparation.prompt
        cost = preparation.cost
        image_base64 = preparation.image_base64
        image_mime = preparation.image_mime

        request_id = uuid4().hex
        logger.info(f"event=ask_ai_enqueue request_id={request_id} profile_id={profile.id}")

        queued = await enqueue_ai_question(
            profile=user_profile,
            prompt=question_text,
            language=profile.language,
            request_id=request_id,
            cost=cost,
            image_base64=image_base64,
            image_mime=image_mime,
        )

        if not queued:
            logger.error(f"event=ask_ai_enqueue_failed request_id={request_id} profile_id={profile.id}")
            await answer_msg(
                message,
                translate(MessageText.coach_agent_error, lang).format(tg=support_contact_url()),
            )
            return

        await notify_request_in_progress(message, lang, show_alert=False)

        state_payload: dict[str, object] = {
            "profile": user_profile.model_dump(mode="json"),
            "last_request_id": request_id,
            "ask_ai_cost": cost,
            "ask_ai_prompt_id": None,
            "ask_ai_prompt_chat_id": None,
            "ask_ai_question_message_id": message.message_id,
        }
        await state.clear()
        await state.update_data(profile=profile.model_dump(mode="json"))
        await state.update_data(**state_payload)
    except Exception:
        logger.exception(f"event=ask_ai_process_failed profile_id={profile.id}")
        await answer_msg(
            message,
            translate(MessageText.coach_agent_error, lang).format(tg=support_contact_url()),
        )
