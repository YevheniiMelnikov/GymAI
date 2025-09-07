import pytest
from httpx import AsyncClient

from ai_coach.application import app
from ai_coach.agent import CoachAgent
from core.enums import CoachType
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


@pytest.mark.asyncio
async def test_program_mode(monkeypatch):
    async def fake_generate(prompt, deps):
        return _sample_program()

    monkeypatch.setattr(CoachAgent, "generate_program", staticmethod(fake_generate))
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.post(
            "/ask/",
            json={"client_id": 1, "prompt": "p", "mode": "program"},
            headers={"X-Agent": "pydanticai"},
        )
    assert resp.status_code == 200
    assert resp.json()["id"] == 1


@pytest.mark.asyncio
async def test_subscription_mode(monkeypatch):
    async def fake_generate(prompt, period, workout_days, deps, wishes=None):
        return _sample_subscription()

    monkeypatch.setattr(CoachAgent, "generate_subscription", staticmethod(fake_generate))
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.post(
            "/ask/",
            json={"client_id": 1, "prompt": "p", "mode": "subscription"},
            headers={"X-Agent": "pydanticai"},
        )
    assert resp.status_code == 200
    assert resp.json()["id"] == 1


@pytest.mark.asyncio
async def test_update_mode(monkeypatch):
    async def fake_update(prompt, expected_workout, feedback, deps):
        return _sample_program()

    monkeypatch.setattr(CoachAgent, "update_program", staticmethod(fake_update))
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.post(
            "/ask/",
            json={"client_id": 1, "prompt": "p", "mode": "update"},
            headers={"X-Agent": "pydanticai"},
        )
    assert resp.status_code == 200
    assert resp.json()["id"] == 1
