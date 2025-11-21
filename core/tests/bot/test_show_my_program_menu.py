import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot import keyboards as kb
from bot.utils import menus
from bot.texts import msg_text
from core.cache import Cache
from core.enums import ClientStatus
from core.exceptions import ProgramNotFoundError
from core.schemas import Client, Profile


class DummyState:
    async def set_state(self, *args, **kwargs) -> None:  # pragma: no cover - interface placeholder
        return None

    async def update_data(self, *args, **kwargs) -> None:  # pragma: no cover - interface placeholder
        return None


def test_show_my_program_menu_uses_client_id(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        profile = Profile(id=2, tg_id=1, language="en")
        client = Client(id=1, profile=2, status=ClientStatus.default)
        called: dict[str, int] = {}

        async def fake_get_client(profile_id: int) -> Client:
            assert profile_id == profile.id
            return client

        async def fake_get_latest_program(client_id: int) -> SimpleNamespace:
            called["id"] = client_id
            return SimpleNamespace(id=1)

        markup = SimpleNamespace()
        answer = AsyncMock(return_value=markup)
        delete = AsyncMock()
        state = DummyState()

        monkeypatch.setattr(Cache.client, "get_client", fake_get_client)
        monkeypatch.setattr(Cache.workout, "get_latest_program", fake_get_latest_program)
        monkeypatch.setattr(kb, "program_action_kb", lambda lang, url: markup)
        monkeypatch.setattr(menus, "get_webapp_url", lambda page, lang=None: "https://webapp")
        monkeypatch.setattr(menus, "answer_msg", answer)
        monkeypatch.setattr(menus, "del_msg", delete)

        cb = SimpleNamespace(message=SimpleNamespace())

        await menus.show_my_program_menu(cb, profile, state)

        assert called["id"] == client.id
        answer.assert_awaited()
        delete.assert_awaited_once_with(cb.message)

    asyncio.run(runner())


def test_show_my_program_menu_alerts_when_no_program(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        profile = Profile(id=2, tg_id=1, language="en")
        client = Client(id=1, profile=2, status=ClientStatus.default)

        async def fake_get_client(profile_id: int) -> Client:
            assert profile_id == profile.id
            return client

        async def fake_get_latest_program(client_id: int) -> None:
            raise ProgramNotFoundError(client_id)

        answer = AsyncMock()
        workouts = AsyncMock()
        state = DummyState()

        monkeypatch.setattr(Cache.client, "get_client", fake_get_client)
        monkeypatch.setattr(Cache.workout, "get_latest_program", fake_get_latest_program)
        monkeypatch.setattr(menus, "show_my_workouts_menu", workouts)

        cb = SimpleNamespace(message=SimpleNamespace(), answer=answer)

        await menus.show_my_program_menu(cb, profile, state)

        answer.assert_awaited_with(msg_text("no_program", profile.language), show_alert=True)
        workouts.assert_awaited_once_with(cb, profile, state)

    asyncio.run(runner())
