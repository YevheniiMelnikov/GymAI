from __future__ import annotations

from typing import Any

from core.cache import Cache
from core.exceptions import ProgramNotFoundError


class States:
    program_action_choice = object()


def msg_text(key: str, lang: str) -> str:
    return key


async def show_program_promo_page(*args: Any, **kwargs: Any) -> None:  # pragma: no cover - placeholder
    return None


async def show_my_program_menu(callback_query: Any, profile: Any, state: Any) -> None:
    client = await Cache.client.get_client(profile.id)
    try:
        await Cache.workout.get_latest_program(client.id)
    except ProgramNotFoundError:
        if hasattr(callback_query, "answer"):
            await callback_query.answer(msg_text("no_program", profile.language), show_alert=True)
        return
    await show_program_promo_page(callback_query, profile, state)
