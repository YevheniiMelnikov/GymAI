from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.states import States

main_router = Router()


@main_router.callback_query(States.client_menu)
async def client_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback_query.data == "my_program":
        await callback_query.message.answer(text="Программа в разработке")
    elif callback_query.data == "feedback":
        await callback_query.message.answer(text="Оцените работу бота: ")
    elif callback_query.data == "my_profile":
        await callback_query.message.answer(text="Ваш профиль: ")
    await callback_query.message.delete()


@main_router.callback_query(States.coach_menu)
async def coach_menu(callback_query: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback_query.data == "show_my_clients":
        await callback_query.message.answer(text="Ваши клиенты: ")
    elif callback_query.data == "feedback":
        await callback_query.message.answer(text="Оцените работу бота: ")
    await callback_query.message.delete()
