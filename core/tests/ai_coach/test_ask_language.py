import asyncio
from enum import Enum
from typing import Any
from types import SimpleNamespace

import pytest  # pyrefly: ignore[import-error]
from httpx import AsyncClient

from ai_coach.agent import CoachAgent
from ai_coach.application import app
from config.app_settings import settings
from core.enums import CoachType, Language, ProfileRole
from core.schemas import Client, DayExercises, Exercise, Profile, Program
from core.services.internal.profile_service import ProfileService


def _sample_program() -> Program:
    day = DayExercises(day="d1", exercises=[Exercise(name="e", sets="1", reps="1")])
    return Program(
        id=1,
        client_profile=1,
        exercises_by_day=[day],
        created_at=0.0,
        split_number=1,
        workout_type="",
        wishes="",
        coach_type=CoachType.human,
    )


async def _run_ask(json_payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    async with AsyncClient(app=app, base_url="http://test") as ac:  # pyrefly: ignore[unexpected-keyword]
        response = await ac.post("/ask/", json=json_payload)
    return response.status_code, response.json()


def test_request_language_overrides_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, str] = {}

    async def fake_generate(
        prompt: str | None,
        deps: Any,
        *,
        workout_type: Any = None,
        **_: Any,
    ) -> Program:
        recorded["locale"] = getattr(deps, "locale")
        return _sample_program()

    async def fake_get_client(self: ProfileService, client_id: int) -> Client | None:
        return Client(id=client_id, profile=10)

    async def fake_get_profile(self: ProfileService, profile_id: int) -> Profile | None:
        return Profile(id=profile_id, role=ProfileRole.client, tg_id=1, language=Language.ru)

    monkeypatch.setattr(CoachAgent, "generate_workout_plan", staticmethod(fake_generate))
    monkeypatch.setattr(ProfileService, "get_client", fake_get_client)
    monkeypatch.setattr(ProfileService, "get_profile", fake_get_profile)

    async def runner() -> None:
        status, _ = await _run_ask(
            {
                "client_id": 1,
                "prompt": "p",
                "mode": "program",
                "language": "ua",
                "workout_type": "home",
            }
        )
        assert status == 200

    asyncio.run(runner())
    assert recorded.get("locale") == "ua"


def test_profile_language_used_when_request_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, str] = {}

    async def fake_generate(
        prompt: str | None,
        deps: Any,
        *,
        workout_type: Any = None,
        **_: Any,
    ) -> Program:
        recorded["locale"] = getattr(deps, "locale")
        return _sample_program()

    async def fake_get_client(self: ProfileService, client_id: int) -> Client | None:
        return Client(id=client_id, profile=20)

    async def fake_get_profile(self: ProfileService, profile_id: int) -> Profile | None:
        return Profile(id=profile_id, role=ProfileRole.client, tg_id=1, language=Language.ua)

    monkeypatch.setattr(CoachAgent, "generate_workout_plan", staticmethod(fake_generate))
    monkeypatch.setattr(ProfileService, "get_client", fake_get_client)
    monkeypatch.setattr(ProfileService, "get_profile", fake_get_profile)

    async def runner() -> None:
        status, _ = await _run_ask(
            {
                "client_id": 2,
                "prompt": "p",
                "mode": "program",
                "workout_type": "home",
            }
        )
        assert status == 200

    asyncio.run(runner())
    assert recorded.get("locale") == "ua"


def test_default_language_used_when_profile_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, str] = {}

    async def fake_generate(
        prompt: str | None,
        deps: Any,
        *,
        workout_type: Any = None,
        **_: Any,
    ) -> Program:
        recorded["locale"] = getattr(deps, "locale")
        return _sample_program()

    async def fake_get_client(self: ProfileService, client_id: int) -> Client | None:
        return None

    async def fake_get_profile(self: ProfileService, profile_id: int) -> Profile | None:
        return None

    monkeypatch.setattr(CoachAgent, "generate_workout_plan", staticmethod(fake_generate))
    monkeypatch.setattr(ProfileService, "get_client", fake_get_client)
    monkeypatch.setattr(ProfileService, "get_profile", fake_get_profile)

    async def runner() -> None:
        status, _ = await _run_ask(
            {
                "client_id": 3,
                "prompt": "p",
                "mode": "program",
                "workout_type": "home",
            }
        )
        assert status == 200

    asyncio.run(runner())
    assert recorded.get("locale") == settings.DEFAULT_LANG


def test_profile_language_enum_without_str(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, str] = {}

    class RawLanguage(Enum):
        ua = "ua"

    async def fake_generate(
        prompt: str | None,
        deps: Any,
        *,
        workout_type: Any = None,
        **_: Any,
    ) -> Program:
        recorded["locale"] = getattr(deps, "locale")
        return _sample_program()

    async def fake_get_client(self: ProfileService, client_id: int) -> Client | None:
        return Client(id=client_id, profile=50)

    async def fake_get_profile(self: ProfileService, profile_id: int) -> Profile | None:
        return SimpleNamespace(id=profile_id, role=ProfileRole.client, tg_id=1, language=RawLanguage.ua)

    monkeypatch.setattr(CoachAgent, "generate_workout_plan", staticmethod(fake_generate))
    monkeypatch.setattr(ProfileService, "get_client", fake_get_client)
    monkeypatch.setattr(ProfileService, "get_profile", fake_get_profile)

    async def runner() -> None:
        status, _ = await _run_ask(
            {
                "client_id": 4,
                "prompt": "p",
                "mode": "program",
                "workout_type": "home",
            }
        )
        assert status == 200

    asyncio.run(runner())
    assert recorded.get("locale") == "ua"
