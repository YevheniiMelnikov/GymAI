import pytest  # pyrefly: ignore[import-error]

from ai_coach.api import DISPATCH
from ai_coach.agent import CoachAgent
from ai_coach.types import CoachMode
from core.schemas import Program, Subscription
from core.enums import WorkoutPlanType, WorkoutType


@pytest.mark.asyncio
async def test_program_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, tuple] = {}

    async def fake_generate(
        prompt: str | None, deps: object, *, workout_type: WorkoutType | None = None, **kwargs
    ) -> str:
        captured["args"] = (prompt, deps, workout_type, kwargs)
        return "program-result"

    monkeypatch.setattr(CoachAgent, "generate_workout_plan", staticmethod(fake_generate))
    ctx = {"prompt": "p", "deps": "d", "wishes": "w", "workout_type": WorkoutType.HOME, "instructions": "i"}
    result = await DISPATCH[CoachMode.program](ctx)  # pyrefly: ignore[bad-argument-type]
    assert result == "program-result"
    assert captured["args"] == (
        "p",
        "d",
        WorkoutType.HOME,
        {"wishes": "w", "instructions": "i", "output_type": Program},
    )


@pytest.mark.asyncio
async def test_subscription_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, tuple] = {}

    async def fake_generate(
        prompt: str | None, deps: object, *, workout_type: WorkoutType | None = None, **kwargs
    ) -> str:
        captured["args"] = (prompt, deps, workout_type, kwargs)
        return "subscription-result"

    monkeypatch.setattr(CoachAgent, "generate_workout_plan", staticmethod(fake_generate))
    ctx = {
        "prompt": "p",
        "period": "1m",
        "workout_days": ["mon"],
        "deps": "d",
        "wishes": "w",
        "workout_type": WorkoutType.HOME,
        "instructions": "i",
    }
    result = await DISPATCH[CoachMode.subscription](ctx)  # pyrefly: ignore[bad-argument-type]
    assert result == "subscription-result"
    assert captured["args"] == (
        "p",
        "d",
        WorkoutType.HOME,
        {
            "period": "1m",
            "workout_days": ["mon"],
            "wishes": "w",
            "instructions": "i",
            "output_type": Subscription,
        },
    )


@pytest.mark.asyncio
async def test_update_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, tuple] = {}

    async def fake_update(
        prompt: str | None,
        expected_workout: str,
        feedback: str,
        *,
        workout_type: WorkoutType | None = None,
        deps=None,
        output_type=None,
        instructions=None,
    ) -> str:
        captured["args"] = (
            prompt,
            expected_workout,
            feedback,
            workout_type,
            deps,
            output_type,
            instructions,
        )
        return "update-result"

    monkeypatch.setattr(CoachAgent, "update_workout_plan", staticmethod(fake_update))
    ctx = {
        "prompt": "p",
        "expected_workout": "ew",
        "feedback": "fb",
        "deps": "d",
        "wishes": "",
        "workout_type": WorkoutType.HOME,
        "plan_type": WorkoutPlanType.PROGRAM,
        "instructions": "i",
    }
    result = await DISPATCH[CoachMode.update](ctx)  # pyrefly: ignore[bad-argument-type]
    assert result == "update-result"
    assert captured["args"] == ("p", "ew", "fb", WorkoutType.HOME, "d", Program, "i")


@pytest.mark.asyncio
async def test_ask_ai_dispatch_and_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, tuple] = {}

    async def fake_answer(prompt: str, deps: object) -> str:
        captured["args"] = (prompt, deps)
        return "ask_ai-result"

    monkeypatch.setattr(CoachAgent, "answer_question", staticmethod(fake_answer))
    ctx = {"prompt": "p", "deps": "d"}
    result = await DISPATCH[CoachMode.ask_ai](ctx)  # pyrefly: ignore[bad-argument-type]
    assert result == "ask_ai-result"
    assert captured["args"] == ("p", "d")
    assert set(DISPATCH) == {
        CoachMode.program,
        CoachMode.subscription,
        CoachMode.update,
        CoachMode.ask_ai,
    }
