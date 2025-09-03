import types
import pytest

from ai_coach.coach_agent import AgentDeps, CoachAgent
from core.schemas import DayExercises, Exercise, Program


@pytest.mark.asyncio
async def test_generate_program_returns_program(monkeypatch):
    async def fake_run(prompt, deps, result_type=None):
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
    deps = AgentDeps(client_id=1)
    result = await CoachAgent.generate_program("hi", deps)
    assert isinstance(result, Program)


@pytest.mark.asyncio
async def test_update_program_returns_program(monkeypatch):
    async def fake_run(prompt, deps, result_type=None):
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
    result = await CoachAgent.update_program("hi", "exp", "fb", deps)
    assert isinstance(result, Program)
