import asyncio
import pytest  # pyrefly: ignore[import-error]
from httpx import AsyncClient

from ai_coach.application import app
from ai_coach.agent import CoachAgent
from core.enums import CoachType, WorkoutType
from core.schemas import DayExercises, Exercise, Program, Subscription


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


def _sample_subscription() -> Subscription:
    day = DayExercises(day="d1", exercises=[Exercise(name="e", sets="1", reps="1")])
    return Subscription(
        id=1,
        client_profile=1,
        enabled=True,
        price=0,
        workout_type="",
        wishes="",
        period="1m",
        workout_days=["mon"],
        exercises=[day],
        payment_date="2024-01-01",
    )


def test_program_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def fake_generate(
            prompt: str,
            deps: object,
            *,
            workout_type: WorkoutType | None = None,
            **kwargs: object,
        ) -> Program:
            assert workout_type is WorkoutType.HOME
            assert kwargs.get("wishes") == "w"
            assert kwargs.get("instructions") == "i"
            assert kwargs.get("output_type") is Program
            return _sample_program()

        monkeypatch.setattr(CoachAgent, "generate_workout_plan", staticmethod(fake_generate))
        async with AsyncClient(app=app, base_url="http://test") as ac:  # pyrefly: ignore[unexpected-keyword]
            resp = await ac.post(
                "/ask/",
                json={
                    "client_id": 1,
                    "prompt": "p",
                    "mode": "program",
                    "wishes": "w",
                    "workout_type": "home",
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
            workout_type: WorkoutType | None = None,
            **kwargs: object,
        ) -> Subscription:
            assert workout_type is WorkoutType.HOME
            assert kwargs.get("period") == "1m"
            assert kwargs.get("workout_days") == ["mon"]
            assert kwargs.get("wishes") == "w"
            assert kwargs.get("instructions") == "i"
            assert kwargs.get("output_type") is Subscription
            return _sample_subscription()

        monkeypatch.setattr(CoachAgent, "generate_workout_plan", staticmethod(fake_generate))
        async with AsyncClient(app=app, base_url="http://test") as ac:  # pyrefly: ignore[unexpected-keyword]
            resp = await ac.post(
                "/ask/",
                json={
                    "client_id": 1,
                    "prompt": "p",
                    "mode": "subscription",
                    "wishes": "w",
                    "workout_type": "home",
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
            workout_type: WorkoutType | None = None,
            deps: object | None = None,
            output_type: type[Program] | None = None,
            instructions: str | None = None,
        ) -> Program:
            assert workout_type is WorkoutType.HOME
            assert output_type is Program
            assert instructions == "i"
            return _sample_program()

        monkeypatch.setattr(CoachAgent, "update_workout_plan", staticmethod(fake_update))
        async with AsyncClient(app=app, base_url="http://test") as ac:  # pyrefly: ignore[unexpected-keyword]
            resp = await ac.post(
                "/ask/",
                json={
                    "client_id": 1,
                    "prompt": "p",
                    "mode": "update",
                    "workout_type": "home",
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
        async with AsyncClient(app=app, base_url="http://test") as ac:  # pyrefly: ignore[unexpected-keyword]
            resp = await ac.post(
                "/ask/",
                json={"client_id": 1, "prompt": "p", "mode": "update", "workout_type": "home"},
                headers={"X-Agent": "pydanticai"},
            )
        assert resp.status_code == 422

    asyncio.run(runner())
