from aiogram import Dispatcher

from bot.handlers.chat_handler import chat_router
from bot.handlers.command_handler import cmd_router
from bot.handlers.invalid_content_handler import invalid_content_router
from bot.handlers.menu_handler import menu_router
from bot.handlers.payment_handler import payment_router
from bot.handlers.questionnaire_handler import questionnaire_router
from bot.handlers.workouts_handler import program_router
from functions.chat import message_router
from schedulers.workout_scheduler import survey_router


def configure_routers(dp: Dispatcher) -> None:
    routers = [
        cmd_router,
        message_router,
        chat_router,
        survey_router,
        menu_router,
        questionnaire_router,
        invalid_content_router,
        program_router,
        payment_router,
    ]
    for router in routers:
        dp.include_router(router)
