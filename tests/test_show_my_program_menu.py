import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.cache import Cache
from core.enums import ClientStatus
from core.exceptions import ProgramNotFoundError
from core.schemas import Client, Profile

from bot.utils import menus
from bot.texts import msg_text


class DummyState:
    async def set_state(self, *args, **kwargs) -> None:  # pragma: no cover - interface placeholder
        return None

    async def update_data(self, *args, **kwargs) -> None:  # pragma: no cover - interface placeholder
        return None


@pytest.mark.asyncio
async def test_show_my_program_menu_uses_client_id(monkeypatch) -> None:
    profile = Profile(id=2, role="client", tg_id=1, language="en")
    client = Client(id=1, profile=2, status=ClientStatus.default, assigned_to=[1])

    async def fake_get_client(profile_id: int) -> Client:
        assert profile_id == profile.id
        return client

    called: dict[str, int] = {}

    async def fake_get_latest_program(client_id: int) -> None:
        called["id"] = client_id
        raise ProgramNotFoundError(client_id)

    monkeypatch.setattr(Cache.client, "get_client", fake_get_client)
    monkeypatch.setattr(Cache.workout, "get_latest_program", fake_get_latest_program)
    monkeypatch.setattr(menus, "show_program_promo_page", AsyncMock())

    cb = SimpleNamespace(message=object())
    state = DummyState()

    await menus.show_my_program_menu(cb, profile, state)

    assert called["id"] == client.id


@pytest.mark.asyncio
async def test_show_my_program_menu_alerts_when_no_program(monkeypatch) -> None:
    profile = Profile(id=2, role="client", tg_id=1, language="en")
    client = Client(id=1, profile=2, status=ClientStatus.default, assigned_to=[1])

    async def fake_get_client(profile_id: int) -> Client:
        assert profile_id == profile.id
        return client

    async def fake_get_latest_program(client_id: int) -> None:
        raise ProgramNotFoundError(client_id)

    answer = AsyncMock()

    monkeypatch.setattr(Cache.client, "get_client", fake_get_client)
    monkeypatch.setattr(Cache.workout, "get_latest_program", fake_get_latest_program)
    monkeypatch.setattr(menus, "show_program_promo_page", AsyncMock())

    cb = SimpleNamespace(message=object(), answer=answer)
    state = DummyState()

    await menus.show_my_program_menu(cb, profile, state)

    answer.assert_awaited_with(msg_text("no_program", profile.language), show_alert=True)
