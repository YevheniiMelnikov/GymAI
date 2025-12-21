import asyncio
import types
from typing import Any
import pytest  # pyrefly: ignore[import-error]

from ai_coach.agent import AgentDeps, CoachAgent
from core.schemas import DayExercises, Exercise, Program, Subscription
from core.enums import WorkoutLocation


def test_generate_plan_returns_program(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def fake_run(
            prompt: str,
            deps: AgentDeps,
            output_type: type[Program] | None = None,
            message_history: list | None = None,
            **kwargs: Any,
        ) -> Program:
            assert message_history is not None
            assert len(message_history) == 2
            return Program(
                id=1,
                profile=deps.profile_id,
                exercises_by_day=[DayExercises(day="d1", exercises=[Exercise(name="squat", sets="3", reps="10")])],
                created_at=0.0,
                split_number=1,
                workout_location="",
                wishes="",
            )

        monkeypatch.setattr(CoachAgent, "_get_agent", classmethod(lambda cls: types.SimpleNamespace(run=fake_run)))

        async def fake_history(cls, profile_id: int) -> list[object]:
            return [object(), object()]

        monkeypatch.setattr(CoachAgent, "_load_history_messages", classmethod(fake_history))
        deps = AgentDeps(profile_id=1)
        result = await CoachAgent.generate_workout_plan(
            "hi", deps, workout_location=WorkoutLocation.HOME, output_type=Program
        )
        assert isinstance(result, Program)

    asyncio.run(runner())


def test_update_workout_plan_returns_program(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def fake_run(
            prompt: str,
            deps: AgentDeps,
            output_type: type[Program] | None = None,
            message_history: list | None = None,
            **kwargs: Any,
        ) -> Program:
            assert "MODE: update" in prompt
            assert "Client Feedback" in prompt
            assert "WORKOUT PROGRAM RULES" in prompt
            assert "Workout location: home" in prompt
            return Program(
                id=2,
                profile=deps.profile_id,
                exercises_by_day=[DayExercises(day="d1", exercises=[Exercise(name="push", sets="2", reps="5")])],
                created_at=0.0,
                split_number=1,
                workout_location="",
                wishes="",
            )

        monkeypatch.setattr(CoachAgent, "_get_agent", classmethod(lambda cls: types.SimpleNamespace(run=fake_run)))
        deps = AgentDeps(profile_id=1)
        result = await CoachAgent.update_workout_plan(
            "hi", "exp", "fb", deps, workout_location=WorkoutLocation.HOME, output_type=Program
        )
        assert isinstance(result, Program)

    asyncio.run(runner())


def test_generate_plan_returns_subscription(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def fake_run(
            prompt: str,
            deps: AgentDeps,
            output_type: type[Subscription] | None = None,
            message_history: list | None = None,
            **kwargs: Any,
        ) -> Subscription:
            assert "MODE: subscription" in prompt
            assert "WORKOUT PROGRAM RULES" in prompt
            assert "Workout location: home" in prompt
            return Subscription(
                id=1,
                profile=deps.profile_id,
                enabled=True,
                price=0,
                workout_location="",
                wishes="",
                period="1m",
                workout_days=["mon"],
                exercises=[],
                payment_date="2024-01-01",
            )

        monkeypatch.setattr(CoachAgent, "_get_agent", classmethod(lambda cls: types.SimpleNamespace(run=fake_run)))
        deps = AgentDeps(profile_id=1)
        result = await CoachAgent.generate_workout_plan(
            "hi",
            deps,
            workout_location=WorkoutLocation.HOME,
            period="1m",
            workout_days=["mon"],
            output_type=Subscription,
        )
        assert isinstance(result, Subscription)

    asyncio.run(runner())


def test_custom_rules_append(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def fake_run(
            prompt: str,
            deps: AgentDeps,
            output_type: type[Program] | None = None,
            message_history: list | None = None,
            **kwargs: Any,
        ) -> Program:
            assert "WORKOUT PROGRAM RULES" in prompt
            assert "extra" in prompt
            return Program(
                id=1,
                profile=deps.profile_id,
                exercises_by_day=[],
                created_at=0.0,
                split_number=1,
                workout_location="",
                wishes="",
            )

        monkeypatch.setattr(CoachAgent, "_get_agent", classmethod(lambda cls: types.SimpleNamespace(run=fake_run)))
        deps = AgentDeps(profile_id=1)
        await CoachAgent.generate_workout_plan(
            "p",
            deps,
            workout_location=WorkoutLocation.HOME,
            output_type=Program,
            instructions="extra",
        )

    asyncio.run(runner())
