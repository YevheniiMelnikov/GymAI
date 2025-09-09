import pytest

from ai_coach.api import DISPATCH
from ai_coach.agent import CoachAgent
from ai_coach.types import CoachMode
from core.schemas import Program, Subscription


@pytest.mark.asyncio
async def test_program_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, tuple] = {}

    async def fake_generate(prompt: str, deps: object, **kwargs) -> str:
        captured["args"] = (prompt, deps, kwargs)
        return "program-result"

    monkeypatch.setattr(CoachAgent, "generate_workout_plan", staticmethod(fake_generate))
    ctx = {"prompt": "p", "deps": "d", "wishes": "w"}
    result = await DISPATCH[CoachMode.program](ctx)
    assert result == "program-result"
    assert captured["args"] == ("p", "d", {"wishes": "w", "result_type": Program})


@pytest.mark.asyncio
async def test_subscription_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, tuple] = {}

    async def fake_generate(prompt: str, deps: object, **kwargs) -> str:
        captured["args"] = (prompt, deps, kwargs)
        return "subscription-result"

    monkeypatch.setattr(CoachAgent, "generate_workout_plan", staticmethod(fake_generate))
    ctx = {
        "prompt": "p",
        "period": "1m",
        "workout_days": ["mon"],
        "deps": "d",
        "wishes": "w",
    }
    result = await DISPATCH[CoachMode.subscription](ctx)
    assert result == "subscription-result"
    assert captured["args"] == (
        "p",
        "d",
        {"period": "1m", "workout_days": ["mon"], "wishes": "w", "result_type": Subscription},
    )


@pytest.mark.asyncio
async def test_update_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, tuple] = {}

    async def fake_update(prompt: str, expected_workout: str, feedback: str, deps: object, result_type=None) -> str:
        captured["args"] = (prompt, expected_workout, feedback, deps, result_type)
        return "update-result"

    monkeypatch.setattr(CoachAgent, "update_workout_plan", staticmethod(fake_update))
    ctx = {
        "prompt": "p",
        "expected_workout": "ew",
        "feedback": "fb",
        "deps": "d",
        "wishes": "",
    }
    result = await DISPATCH[CoachMode.update](ctx)
    assert result == "update-result"
    assert captured["args"] == ("p", "ew", "fb", "d", Program)


@pytest.mark.asyncio
async def test_ask_ai_dispatch_and_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, tuple] = {}

    async def fake_answer(prompt: str, deps: object) -> str:
        captured["args"] = (prompt, deps)
        return "ask_ai-result"

    monkeypatch.setattr(CoachAgent, "answer_question", staticmethod(fake_answer))
    ctx = {"prompt": "p", "deps": "d"}
    result = await DISPATCH[CoachMode.ask_ai](ctx)
    assert result == "ask_ai-result"
    assert captured["args"] == ("p", "d")
    assert set(DISPATCH) == {
        CoachMode.program,
        CoachMode.subscription,
        CoachMode.update,
        CoachMode.ask_ai,
    }
