from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiogram import Dispatcher, Router
else:  # pragma: no cover - runtime imports
    Dispatcher = Router = Any

from bot.handlers.admin_handler import admin_router
from bot.handlers.chat_handler import chat_router
from bot.handlers.command_handler import cmd_router
from bot.handlers.invalid_content_handler import invalid_content_router
from bot.handlers.menu_handler import menu_router
from bot.handlers.payment_handler import payment_router
from bot.handlers.questionnaire_handler import questionnaire_router
from bot.handlers.workout_handler import workout_router


def configure_routers(dp: "Dispatcher") -> None:
    routers: list["Router"] = [
        admin_router,
        cmd_router,
        questionnaire_router,
        menu_router,
        payment_router,
        workout_router,
        chat_router,
        invalid_content_router,
    ]
    for router in routers:
        dp.include_router(router)
