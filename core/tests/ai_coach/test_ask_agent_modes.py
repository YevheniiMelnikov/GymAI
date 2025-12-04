import asyncio
import pytest  # pyrefly: ignore[import-error]
from httpx import AsyncClient, ASGITransport

from ai_coach.application import app
from ai_coach.agent import CoachAgent
import ai_coach.api as coach_api
from ai_coach.api import DEFAULT_WORKOUT_DAYS
from core.enums import WorkoutLocation
from core.schemas import DayExercises, Exercise, Program, Subscription


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


def _sample_subscription() -> Subscription:
    day = DayExercises(day="d1", exercises=[Exercise(name="e", sets="1", reps="1")])
    return Subscription(
        id=1,
        profile=1,
        enabled=True,
        price=0,
        workout_location="",
        wishes="",
        period="1m",
        workout_days=["mon"],
        exercises=[day],
        payment_date="2024-01-01",
    )


def _patch_agent(monkeypatch: pytest.MonkeyPatch, attr: str, value) -> None:
    monkeypatch.setattr(CoachAgent, attr, value)
    monkeypatch.setattr(coach_api.CoachAgent, attr, value)


def test_program_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def fake_generate(
            prompt: str,
            deps: object,
            *,
            workout_location: WorkoutLocation | None = None,
            **kwargs: object,
        ) -> Program:
            assert workout_location is WorkoutLocation.HOME
            assert kwargs.get("wishes") == "w"
            assert kwargs.get("instructions") == "i"
            assert kwargs.get("output_type") is Program
            return _sample_program()

        _patch_agent(monkeypatch, "generate_workout_plan", staticmethod(fake_generate))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/ask/",
                json={
                    "profile_id": 1,
                    "prompt": "p",
                    "mode": "program",
                    "wishes": "w",
                    "workout_location": "home",
                    "instructions": "i",
                },
                headers={"X-Agent": "pydanticai"},
            )
        assert resp.status_code == 200
        assert resp.json()["id"] == 1

    asyncio.run(runner())


def test_subscription_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def fake_generate(
            prompt: str,
            deps: object,
            *,
            workout_location: WorkoutLocation | None = None,
            **kwargs: object,
        ) -> Subscription:
            assert workout_location is WorkoutLocation.HOME
            assert kwargs.get("period") == "1m"
            assert kwargs.get("workout_days") == list(DEFAULT_WORKOUT_DAYS)
            assert kwargs.get("wishes") == "w"
            assert kwargs.get("instructions") == "i"
            assert kwargs.get("output_type") is Subscription
            return _sample_subscription()

        _patch_agent(monkeypatch, "generate_workout_plan", staticmethod(fake_generate))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/ask/",
                json={
                    "profile_id": 1,
                    "prompt": "p",
                    "mode": "subscription",
                    "wishes": "w",
                    "workout_location": "home",
                    "instructions": "i",
                },
                headers={"X-Agent": "pydanticai"},
            )
        assert resp.status_code == 200
        assert resp.json()["id"] == 1

    asyncio.run(runner())


def test_update_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def fake_update(
            prompt: str,
            expected_workout: object,
            feedback: object,
            *,
            workout_location: WorkoutLocation | None = None,
            deps: object | None = None,
            output_type: type[Program] | None = None,
            instructions: str | None = None,
        ) -> Program:
            assert workout_location is WorkoutLocation.HOME
            assert output_type is Program
            assert instructions == "i"
            return _sample_program()

        _patch_agent(monkeypatch, "update_workout_plan", staticmethod(fake_update))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/ask/",
                json={
                    "profile_id": 1,
                    "prompt": "p",
                    "mode": "update",
                    "workout_location": "home",
                    "plan_type": "program",
                    "instructions": "i",
                },
                headers={"X-Agent": "pydanticai"},
            )
        assert resp.status_code == 200
        assert resp.json()["id"] == 1

    asyncio.run(runner())


def test_update_requires_plan_type() -> None:
    async def runner() -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/ask/",
                json={"profile_id": 1, "prompt": "p", "mode": "update", "workout_location": "home"},
                headers={"X-Agent": "pydanticai"},
            )
        assert resp.status_code == 422

    asyncio.run(runner())
