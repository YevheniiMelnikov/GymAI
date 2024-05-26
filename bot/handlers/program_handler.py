from contextlib import suppress

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import incoming_message, program_manage_menu
from bot.states import States
from common.functions import send_message, show_main_menu
from common.user_service import user_service
from common.utils import format_program
from texts.text_manager import MessageText, translate

program_router = Router()


@program_router.callback_query(States.program_manage)
async def program_manage(callback_query: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    data = await state.get_data()
    client_id = data.get("client_id")

    if callback_query.data == "quit":
        await show_main_menu(callback_query.message, profile, state)
        await state.set_state(States.main_menu)

    if callback_query.data == "reset":
        await state.clear()
        await callback_query.message.answer(text=translate(MessageText.enter_exercise, lang=profile.language))
        await state.set_state(States.program_manage)
        await state.update_data(client_id=client_id, exercises=[])
        await callback_query.message.delete()

    elif callback_query.data == "save":
        if exercises := data.get("exercises", []):
            await user_service.save_program(client_id, exercises)
            await callback_query.answer(text=translate(MessageText.saved, lang=profile.language))
            client = user_service.storage.get_client_by_id(client_id)
            program = format_program(exercises)
            client_lang = user_service.storage.get_profile_info_by_key(client.tg_id, client.id, "language")
            await send_message(
                recipient=client,
                text=translate(MessageText.new_program, lang=client_lang),
                bot=bot,
                state=state,
                include_incoming_message=False,
            )
            await send_message(
                recipient=client,
                text=translate(MessageText.current_program, lang=profile.language).format(program=program),
                bot=bot,
                state=state,
                reply_markup=incoming_message(profile.language, profile.id),
                include_incoming_message=False,
            )
            await state.clear()
            await state.set_state(States.main_menu)
            await show_main_menu(callback_query.message, profile, state)
        else:
            await callback_query.answer(text=translate(MessageText.no_exercises_to_save, lang=profile.language))


@program_router.message(States.program_manage)
async def adding_exercise(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile = user_service.storage.get_current_profile(message.from_user.id)
    exercises = data.get("exercises", [])
    exercises.append(message.text)
    program = format_program(exercises)

    if del_msg := data.get("del_msg"):
        with suppress(TelegramBadRequest):
            await message.bot.delete_message(message.chat.id, del_msg)
    if del_msg := data.get("exercise_msg"):
        with suppress(TelegramBadRequest):
            await message.bot.delete_message(message.chat.id, del_msg)
    if del_msg := data.get("program_msg"):
        with suppress(TelegramBadRequest):
            await message.bot.delete_message(message.chat.id, del_msg)

    exercise_msg = await message.answer(translate(MessageText.enter_exercise, profile.language))
    program_msg = await exercise_msg.answer(
        text=translate(MessageText.current_program, profile.language).format(program=program),
        reply_markup=program_manage_menu(profile.language),
    )
    await state.update_data(
        exercise_msg=exercise_msg.message_id,
        program_msg=program_msg.message_id,
        exercises=exercises,
    )

    await message.delete()
