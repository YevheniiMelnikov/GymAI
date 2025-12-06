import asyncio
from enum import Enum
from typing import Any
from types import SimpleNamespace

import pytest  # pyrefly: ignore[import-error]
from httpx import AsyncClient, ASGITransport

from ai_coach.agent import CoachAgent
import ai_coach.api as coach_api
from ai_coach.application import app
from config.app_settings import settings
from core.enums import Language
from core.schemas import DayExercises, Exercise, Profile, Program


def _sample_program() -> Program:
    day = DayExercises(day="d1", exercises=[Exercise(name="e", sets="1", reps="1")])
    return Program(
        id=1,
        profile=1,
        exercises_by_day=[day],
        created_at=0.0,
        split_number=1,
        workout_location="",
        wishes="",
    )


async def _run_ask(json_payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/coach/plan/", json=json_payload)
    return response.status_code, response.json()


def _patch_agent(monkeypatch: pytest.MonkeyPatch, attr: str, value) -> None:
    monkeypatch.setattr(CoachAgent, attr, value)
    monkeypatch.setattr(coach_api.CoachAgent, attr, value)


def test_request_language_overrides_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, str] = {}

    async def fake_generate(
        prompt: str | None,
        deps: Any,
        *,
        workout_location: Any = None,
        **_: Any,
    ) -> Program:
        recorded["locale"] = getattr(deps, "locale")
        return _sample_program()

    async def fake_get_profile(profile_id: int) -> Profile | None:
        return Profile(id=profile_id, tg_id=1, language=Language.ru)

    _patch_agent(monkeypatch, "generate_workout_plan", staticmethod(fake_generate))
    monkeypatch.setattr("core.services.internal.APIService.profile.get_profile", fake_get_profile)

    async def runner() -> None:
        status, _ = await _run_ask(
            {
                "profile_id": 1,
                "prompt": "p-request-language",
                "mode": "program",
                "language": "ua",
                "workout_location": "home",
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
        workout_location: Any = None,
        **_: Any,
    ) -> Program:
        recorded["locale"] = getattr(deps, "locale")
        return _sample_program()

    async def fake_get_profile(profile_id: int) -> Profile | None:
        return Profile(id=profile_id, tg_id=1, language=Language.ua)

    _patch_agent(monkeypatch, "generate_workout_plan", staticmethod(fake_generate))
    monkeypatch.setattr("core.services.internal.APIService.profile.get_profile", fake_get_profile)

    async def runner() -> None:
        status, _ = await _run_ask(
            {
                "profile_id": 2,
                "prompt": "p-profile-language",
                "mode": "program",
                "workout_location": "home",
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
        workout_location: Any = None,
        **_: Any,
    ) -> Program:
        recorded["locale"] = getattr(deps, "locale")
        return _sample_program()

    async def fake_get_profile(profile_id: int) -> Profile | None:
        return None

    _patch_agent(monkeypatch, "generate_workout_plan", staticmethod(fake_generate))
    monkeypatch.setattr("core.services.internal.APIService.profile.get_profile", fake_get_profile)

    async def runner() -> None:
        status, _ = await _run_ask(
            {
                "profile_id": 3,
                "prompt": "p-default-language",
                "mode": "program",
                "workout_location": "home",
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
        workout_location: Any = None,
        **_: Any,
    ) -> Program:
        recorded["locale"] = getattr(deps, "locale")
        return _sample_program()

    async def fake_get_profile(profile_id: int) -> Profile | None:
        return SimpleNamespace(id=profile_id, tg_id=1, language=RawLanguage.ua)

    _patch_agent(monkeypatch, "generate_workout_plan", staticmethod(fake_generate))
    monkeypatch.setattr("core.services.internal.APIService.profile.get_profile", fake_get_profile)

    async def runner() -> None:
        status, _ = await _run_ask(
            {
                "profile_id": 4,
                "prompt": "p-enum-language",
                "mode": "program",
                "workout_location": "home",
            }
        )
        assert status == 200

    asyncio.run(runner())
    assert recorded.get("locale") == "ua"
