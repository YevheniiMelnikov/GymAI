from __future__ import annotations

import inspect
from typing import Any

import django

from core.containers import create_container, get_container, set_container
from core.services import APIService


def setup_django() -> None:
    django.setup()


def configure_api_service() -> Any:
    container = create_container()
    set_container(container)
    APIService.configure(get_container)
    return container


async def init_container(container: Any) -> None:
    init_resources = container.init_resources()
    if inspect.isawaitable(init_resources):
        await init_resources


async def shutdown_container(container: Any) -> None:
    shutdown_resources = container.shutdown_resources()
    if inspect.isawaitable(shutdown_resources):
        await shutdown_resources
