from contextlib import suppress

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.keyboards import program_edit_kb, program_manage_menu, program_view_kb, subscription_view_kb
from bot.states import States
from common.functions.chat import send_message
from common.functions.menus import show_main_menu
from common.functions.text_utils import format_program
from common.models import Profile
from common.user_service import user_service
from texts.text_manager import ButtonText, MessageText, translate


async def save_workout_plan(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    data = await state.get_data()
    completed_days = data.get("day_index", 0)
    split_number = data.get("split")
    client_id = data.get("client_id")
    if exercises := data.get("exercises", {}):
        if completed_days == split_number:
            await callback_query.answer(text=translate(MessageText.saved, lang=profile.language))
            client = user_service.storage.get_client_by_id(client_id)
            client_lang = user_service.storage.get_profile_info_by_key(client.tg_id, client.id, "language")
            if data.get("subscription"):
                subscription_data = user_service.storage.get_subscription(client_id).to_dict()
                subscription_data.update(user=client_id, exercises=exercises)
                user_service.storage.save_subscription(client_id, subscription_data)
                await user_service.update_subscription(subscription_data.get("id"), subscription_data)
                await send_message(
                    recipient=client,
                    text=translate(MessageText.new_program, lang=client_lang),
                    state=state,
                    reply_markup=subscription_view_kb(client_lang),
                    include_incoming_message=False,
                )
            else:
                program = await format_program(exercises, 0)
                await user_service.save_program(str(client_id), exercises, split_number)
                await send_message(
                    recipient=client,
                    text=translate(MessageText.new_program, lang=client_lang),
                    state=state,
                    include_incoming_message=False,
                )
                await send_message(
                    recipient=client,
                    text=translate(MessageText.program_page, lang=client_lang).format(program=program, day=1),
                    state=state,
                    reply_markup=program_view_kb(client_lang),
                    include_incoming_message=False,
                )
            await state.clear()
            await show_main_menu(callback_query.message, profile, state)
        else:
            await callback_query.answer(translate(MessageText.complete_all_days, profile.language), show_alert=True)
    else:
        await callback_query.answer(text=translate(MessageText.no_exercises_to_save, lang=profile.language))


async def reset_workout_plan(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    data = await state.get_data()
    client_id = data.get("client_id")
    await callback_query.answer(translate(ButtonText.done, profile.language))
    if data.get("subscription"):
        subscription_data = user_service.storage.get_subscription(client_id).to_dict()
        subscription_data.update(user=client_id, exercises=None)
        await user_service.update_subscription(subscription_data.get("id"), subscription_data)
        await user_service.storage.save_subscription(client_id, subscription_data)
    else:
        if await user_service.delete_program(str(client_id)):
            user_service.storage.delete_program(str(client_id))
            user_service.storage.set_payment_status(str(client_id), True, "program")
    await state.clear()
    await callback_query.message.answer(translate(MessageText.enter_daily_program, profile.language).format(day=1))
    await state.update_data(client_id=client_id, exercises=[], day_index=0)
    await state.set_state(States.program_manage)
    with suppress(TelegramBadRequest):
        await callback_query.message.delete()


async def next_day_workout_plan(callback_query: CallbackQuery, state: FSMContext) -> None:
    profile = user_service.storage.get_current_profile(callback_query.from_user.id)
    data = await state.get_data()
    completed_days = data.get("day_index", 0)
    split_number = data.get("split")
    if exercises := data.get("exercises", {}):
        if completed_days < split_number:
            await callback_query.answer(translate(ButtonText.prev_menu))

            if "program_msg" in data:
                with suppress(TelegramBadRequest):
                    await callback_query.message.bot.delete_message(callback_query.message.chat.id, data["program_msg"])

            program = await format_program(exercises, completed_days)
            program_msg = await callback_query.message.answer(
                text=translate(MessageText.program_page, profile.language).format(
                    program=program, day=completed_days + 1
                ),
                reply_markup=program_manage_menu(profile.language),
            )
            await state.update_data(program_msg=program_msg.message_id)
            with suppress(TelegramBadRequest):
                await callback_query.message.delete()
        else:
            await callback_query.answer(translate(MessageText.out_of_range, profile.language))
    else:
        await callback_query.answer(text=translate(MessageText.no_exercises_to_save, lang=profile.language))


async def manage_program(callback_query: CallbackQuery, profile: Profile, client_id: str, state: FSMContext) -> None:
    program_paid = user_service.storage.check_payment_status(client_id, "program")
    workout_data = user_service.storage.get_program(str(client_id))

    if not program_paid and not workout_data:
        await callback_query.answer(
            text=translate(MessageText.payment_required, lang=profile.language), show_alert=True
        )
        return

    if workout_data and workout_data.exercises_by_day:
        program = await format_program(workout_data.exercises_by_day, 0)
        del_msg = await callback_query.message.answer(
            text=translate(MessageText.program_page, lang=profile.language).format(program=program, day=1),
            reply_markup=program_edit_kb(profile.language),
            disable_web_page_preview=True,
        )
        await state.update_data(
            exercises=workout_data.exercises_by_day, del_msg=del_msg.message_id, client_id=client_id, day_index=0
        )
        await state.set_state(States.program_edit)
        await callback_query.message.delete()
        return

    else:
        del_msg = await callback_query.message.answer(text=translate(MessageText.no_program, lang=profile.language))

    await state.update_data(del_msg=del_msg.message_id, client_id=client_id)
    await callback_query.message.answer(translate(MessageText.workouts_number, profile.language))
    await state.set_state(States.workouts_number)
    await callback_query.message.delete()
