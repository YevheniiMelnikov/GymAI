import asyncio
import types
from typing import Any
import pytest  # pyrefly: ignore[import-error]

from ai_coach.agent import AgentDeps, CoachAgent
from core.schemas import DayExercises, Exercise, Program, Subscription
from core.enums import WorkoutType


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
                client_profile=deps.client_id,
                exercises_by_day=[DayExercises(day="d1", exercises=[Exercise(name="squat", sets="3", reps="10")])],
                created_at=0.0,
                split_number=1,
                workout_type="",
                wishes="",
            )

        monkeypatch.setattr(CoachAgent, "_get_agent", classmethod(lambda cls: types.SimpleNamespace(run=fake_run)))
        monkeypatch.setattr(CoachAgent, "_message_history", staticmethod(lambda client_id: [object(), object()]))
        deps = AgentDeps(client_id=1)
        result = await CoachAgent.generate_workout_plan("hi", deps, workout_type=WorkoutType.HOME, output_type=Program)
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
            assert "Workout type: home" in prompt
            return Program(
                id=2,
                client_profile=deps.client_id,
                exercises_by_day=[DayExercises(day="d1", exercises=[Exercise(name="push", sets="2", reps="5")])],
                created_at=0.0,
                split_number=1,
                workout_type="",
                wishes="",
            )

        monkeypatch.setattr(CoachAgent, "_get_agent", classmethod(lambda cls: types.SimpleNamespace(run=fake_run)))
        deps = AgentDeps(client_id=1)
        result = await CoachAgent.update_workout_plan(
            "hi", "exp", "fb", deps, workout_type=WorkoutType.HOME, output_type=Program
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
            assert "Workout type: home" in prompt
            return Subscription(
                id=1,
                client_profile=deps.client_id,
                enabled=True,
                price=0,
                workout_type="",
                wishes="",
                period="1m",
                workout_days=["mon"],
                exercises=[],
                payment_date="2024-01-01",
            )

        monkeypatch.setattr(CoachAgent, "_get_agent", classmethod(lambda cls: types.SimpleNamespace(run=fake_run)))
        deps = AgentDeps(client_id=1)
        result = await CoachAgent.generate_workout_plan(
            "hi",
            deps,
            workout_type=WorkoutType.HOME,
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
                client_profile=deps.client_id,
                exercises_by_day=[],
                created_at=0.0,
                split_number=1,
                workout_type="",
                wishes="",
            )

        monkeypatch.setattr(CoachAgent, "_get_agent", classmethod(lambda cls: types.SimpleNamespace(run=fake_run)))
        deps = AgentDeps(client_id=1)
        await CoachAgent.generate_workout_plan(
            "p",
            deps,
            workout_type=WorkoutType.HOME,
            output_type=Program,
            instructions="extra",
        )

    asyncio.run(runner())
