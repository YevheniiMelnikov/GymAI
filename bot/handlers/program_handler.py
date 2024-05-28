from contextlib import suppress

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import incoming_message, program_manage_menu
from bot.states import States
from common.functions import find_related_gif, format_program, send_message, short_url, show_main_menu
from common.user_service import user_service
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
            await user_service.save_program(str(client_id), [exercise[0] for exercise in exercises])
            await callback_query.answer(text=translate(MessageText.saved, lang=profile.language))
            client = user_service.storage.get_client_by_id(client_id)
            program = await format_program(exercises)
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
    if link_to_gif := await find_related_gif(message.text):
        shorted_link = await short_url(link_to_gif)
        exercises.append((message.text, shorted_link))
    else:
        exercises.append((message.text,))

    if link_to_gif:
        gif_file_name = link_to_gif.split("/")[-1]
        user_service.storage.cache_gif_filename(message.text, gif_file_name)

    program = await format_program(exercises)

    for msg_key in ["del_msg", "exercise_msg", "program_msg"]:
        if del_msg := data.get(msg_key):
            with suppress(TelegramBadRequest):
                await message.bot.delete_message(message.chat.id, del_msg)

    exercise_msg = await message.answer(translate(MessageText.enter_exercise, profile.language))
    program_msg = await exercise_msg.answer(
        text=translate(MessageText.current_program, profile.language).format(program=program),
        reply_markup=program_manage_menu(profile.language),
        disable_web_page_preview=True,
    )
    await state.update_data(
        exercise_msg=exercise_msg.message_id,
        program_msg=program_msg.message_id,
        exercises=exercises,
    )
    await message.delete()
