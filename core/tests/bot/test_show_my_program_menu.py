import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot import keyboards as kb
from bot.utils import menus
from core.schemas import Profile


class DummyState:
    async def set_state(self, *args, **kwargs) -> None:  # pragma: no cover - interface placeholder
        return None

    async def update_data(self, *args, **kwargs) -> None:  # pragma: no cover - interface placeholder
        return None


def test_show_my_program_menu_shows_action_keyboard(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        profile = Profile(id=2, tg_id=1, language="en")
        markup = SimpleNamespace()
        answer = AsyncMock(return_value=markup)
        delete = AsyncMock()
        state = DummyState()

        monkeypatch.setattr(kb, "program_action_kb", lambda lang, url: markup)
        monkeypatch.setattr(menus, "get_webapp_url", lambda page, lang=None: "https://webapp")
        monkeypatch.setattr(menus, "answer_msg", answer)
        monkeypatch.setattr(menus, "del_msg", delete)

        cb = SimpleNamespace(message=SimpleNamespace())

        await menus.show_my_program_menu(cb, profile, state)

        answer.assert_awaited_once()
        delete.assert_awaited_once_with(cb.message)

    asyncio.run(runner())
