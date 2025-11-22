import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot import keyboards as kb
from bot.utils import menus
from bot.texts import MessageText, msg_text
from core.cache import Cache
from core.enums import ProfileStatus
from core.exceptions import ProgramNotFoundError
from core.schemas import Profile


class DummyState:
    async def set_state(self, *args, **kwargs) -> None:  # pragma: no cover - interface placeholder
        return None

    async def update_data(self, *args, **kwargs) -> None:  # pragma: no cover - interface placeholder
        return None


def test_show_my_program_menu_uses_profile_id(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        profile = Profile(id=2, tg_id=1, language="en")
        cached_profile = Profile(id=2, tg_id=1, language="en", status=ProfileStatus.default)
        called: dict[str, int] = {}

        async def fake_get_profile(profile_id: int) -> Profile:
            assert profile_id == profile.id
            return cached_profile

        async def fake_get_latest_program(profile_id: int) -> SimpleNamespace:
            called["id"] = profile_id
            return SimpleNamespace(id=1)

        markup = SimpleNamespace()
        answer = AsyncMock(return_value=markup)
        delete = AsyncMock()
        state = DummyState()

        monkeypatch.setattr(Cache.profile, "get_record", fake_get_profile)
        monkeypatch.setattr(Cache.workout, "get_latest_program", fake_get_latest_program)
        monkeypatch.setattr(kb, "program_action_kb", lambda lang, url: markup)
        monkeypatch.setattr(menus, "get_webapp_url", lambda page, lang=None: "https://webapp")
        monkeypatch.setattr(menus, "answer_msg", answer)
        monkeypatch.setattr(menus, "del_msg", delete)

        cb = SimpleNamespace(message=SimpleNamespace())

        await menus.show_my_program_menu(cb, profile, state)

        assert called["id"] == cached_profile.id
        answer.assert_awaited()
        delete.assert_awaited_once_with(cb.message)

    asyncio.run(runner())


def test_show_my_program_menu_alerts_when_no_program(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        profile = Profile(id=2, tg_id=1, language="en")
        cached_profile = Profile(id=2, tg_id=1, language="en", status=ProfileStatus.default)

        async def fake_get_profile(profile_id: int) -> Profile:
            assert profile_id == profile.id
            return cached_profile

        async def fake_get_latest_program(profile_id: int) -> None:
            raise ProgramNotFoundError(profile_id)

        answer = AsyncMock()
        workouts = AsyncMock()
        state = DummyState()

        monkeypatch.setattr(Cache.profile, "get_record", fake_get_profile)
        monkeypatch.setattr(Cache.workout, "get_latest_program", fake_get_latest_program)
        monkeypatch.setattr(menus, "show_my_workouts_menu", workouts)

        cb = SimpleNamespace(message=SimpleNamespace(), answer=answer)

        await menus.show_my_program_menu(cb, profile, state)

        answer.assert_awaited_with(msg_text(MessageText.no_program, profile.language), show_alert=True)
        workouts.assert_awaited_once_with(cb, profile, state)

    asyncio.run(runner())
