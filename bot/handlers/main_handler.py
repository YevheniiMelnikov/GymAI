from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import client_menu_keyboard, coach_menu_keyboard, language_choice
from bot.states import States
from common.functions import get_person
from texts.text_manager import MessageText, translate

main_router = Router()


@main_router.message(States.main_menu)
async def main_menu(message: Message, state: FSMContext) -> None:
    if person := await get_person(message.from_user.id):
        if person.status == "client":
            await state.set_state(States.client_menu)
            await message.answer(
                translate(MessageText.welcome, lang=person.language).format(name=person.short_name),
                reply_markup=client_menu_keyboard(person.language, person.short_name),
            )
        elif person.status == "coach":
            await state.set_state(States.coach_menu)
            await message.answer(
                translate(MessageText.welcome, lang=person.language).format(name=person.short_name),
                reply_markup=coach_menu_keyboard(person.language, person.short_name),
            )
    else:
        await state.set_state(States.language_choice)
        await message.answer(text=translate(MessageText.choose_language), reply_markup=language_choice())


@main_router.callback_query(States.client_menu)
async def client_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback_query.message.delete()
    if callback_query.data == "my_program":
        await callback_query.message.answer(text="Программа в разработке")
    elif callback_query.data == "feedback":
        await callback_query.message.answer(text="Оцените работу бота: ")
    elif callback_query.data == "my_profile":
        await callback_query.message.answer(text="Ваш профиль: ")


@main_router.callback_query(States.coach_menu)
async def coach_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback_query.message.delete()
    if callback_query.data == "show_my_clients":
        await callback_query.message.answer(text="Ваши клиенты: ")
    elif callback_query.data == "feedback":
        await callback_query.message.answer(text="Оцените работу бота: ")
    elif callback_query.data == "my_profile":
        await callback_query.message.answer(text="Ваш профиль: ")
