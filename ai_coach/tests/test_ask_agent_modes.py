import asyncio
import pytest  # pyrefly: ignore[import-error]

from ai_coach.api import ask
from ai_coach.agent import CoachAgent
from ai_coach.schemas import AICoachRequest
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


def test_program_mode(monkeypatch):
    async def fake_generate(prompt, deps, *, workout_type: WorkoutType | None = None, **kwargs):
        assert workout_type is WorkoutType.HOME
        assert kwargs.get("wishes") == "w"
        assert kwargs.get("instructions") == "i"
        assert kwargs.get("output_type") is Program
        return _sample_program()

    monkeypatch.setattr(CoachAgent, "generate_workout_plan", staticmethod(fake_generate))
    req = AICoachRequest(
        client_id=1,
        prompt="p",
        mode="program",
        wishes="w",
        workout_type="home",
        instructions="i",
    )
    result = asyncio.run(ask(req, object()))
    assert isinstance(result, Program) and result.id == 1


def test_subscription_mode(monkeypatch):
    async def fake_generate(prompt, deps, *, workout_type: WorkoutType | None = None, **kwargs):
        assert workout_type is WorkoutType.HOME
        assert kwargs.get("period") == "1m"
        assert kwargs.get("workout_days") == ["mon"]
        assert kwargs.get("wishes") == "w"
        assert kwargs.get("instructions") == "i"
        assert kwargs.get("output_type") is Subscription
        return _sample_subscription()

    monkeypatch.setattr(CoachAgent, "generate_workout_plan", staticmethod(fake_generate))
    req = AICoachRequest(
        client_id=1,
        prompt="p",
        mode="subscription",
        wishes="w",
        workout_type="home",
        instructions="i",
        workout_days=["mon"],
        period="1m",
    )
    result = asyncio.run(ask(req, object()))
    assert isinstance(result, Subscription) and result.id == 1


def test_update_mode(monkeypatch):
    async def fake_update(
        prompt,
        expected_workout,
        feedback,
        *,
        workout_type: WorkoutType | None = None,
        deps=None,
        output_type=None,
        instructions=None,
    ):
        assert workout_type is WorkoutType.HOME
        assert output_type is Program
        assert instructions == "i"
        return _sample_program()

    monkeypatch.setattr(CoachAgent, "update_workout_plan", staticmethod(fake_update))
    req = AICoachRequest(
        client_id=1,
        prompt="p",
        mode="update",
        workout_type="home",
        plan_type="program",
        instructions="i",
    )
    result = asyncio.run(ask(req, object()))
    assert isinstance(result, Program) and result.id == 1


def test_update_requires_plan_type() -> None:
    with pytest.raises(ValueError):
        AICoachRequest(client_id=1, prompt="p", mode="update", workout_type="home")
