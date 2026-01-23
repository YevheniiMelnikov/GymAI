from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ("configure_routers",)

if TYPE_CHECKING:
    from aiogram import Dispatcher
else:
    Dispatcher = Any


def configure_routers(dp: "Dispatcher") -> None:
    from .routers_collector import configure_routers as _configure

    _configure(dp)
