from contextlib import suppress
from typing import cast
from uuid import uuid4

from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest

from loguru import logger

from bot.states import States
from bot.utils.menus import show_main_menu
from bot.utils.bot import del_msg, answer_msg
from bot.utils.ai_coach import enqueue_ai_question
from bot.utils.ask_ai import prepare_ask_ai_request
from core.schemas import Profile
from bot.texts import MessageText, translate
from core.exceptions import AskAiPreparationError
from config.app_settings import settings

workout_router = Router()


@workout_router.callback_query(States.ask_ai_question)
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
    else:
        await state.set_state(States.main_menu)


@workout_router.message(States.ask_ai_question)
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
                translate(MessageText.coach_agent_error, lang).format(tg=settings.TG_SUPPORT_CONTACT),
            )
            return

        await answer_msg(message, translate(MessageText.request_in_progress, lang))

        state_payload: dict[str, object] = {
            "profile": user_profile.model_dump(mode="json"),
            "last_request_id": request_id,
            "ask_ai_cost": cost,
            "ask_ai_prompt_id": None,
            "ask_ai_prompt_chat_id": None,
            "ask_ai_question_message_id": message.message_id,
        }
        await show_main_menu(message, profile, state, delete_source=False)
        await state.update_data(**state_payload)
    except Exception:
        logger.exception(f"event=ask_ai_process_failed profile_id={profile.id}")
        await answer_msg(
            message,
            translate(MessageText.coach_agent_error, lang).format(tg=settings.TG_SUPPORT_CONTACT),
        )


@workout_router.callback_query(States.workout_survey)
async def send_workout_results(callback_query: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    profile = Profile.model_validate(data["profile"])
    if callback_query.data == "completed":
        await callback_query.answer()
        await callback_query.answer(translate(MessageText.keep_going, profile.language), show_alert=True)
        message = cast(Message, callback_query.message)
        assert message is not None
        await show_main_menu(message, profile, state)
        await del_msg(cast(Message | CallbackQuery | None, callback_query))
    else:
        await callback_query.answer(translate(MessageText.workout_description, profile.language), show_alert=True)
