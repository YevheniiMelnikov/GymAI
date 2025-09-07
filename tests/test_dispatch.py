import pytest

from ai_coach.api import DISPATCH
from ai_coach.coach_agent import CoachAgent
from ai_coach.types import CoachMode


@pytest.mark.asyncio
async def test_program_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, tuple] = {}

    async def fake_generate(prompt: str, deps: object) -> str:
        captured["args"] = (prompt, deps)
        return "program-result"

    monkeypatch.setattr(CoachAgent, "generate_program", staticmethod(fake_generate))
    ctx = {"prompt": "p", "deps": "d"}
    result = await DISPATCH[CoachMode.program](ctx)
    assert result == "program-result"
    assert captured["args"] == ("p", "d")


@pytest.mark.asyncio
async def test_subscription_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, tuple] = {}

    async def fake_generate(prompt: str, period: str, workout_days: list[str], deps: object) -> str:
        captured["args"] = (prompt, period, tuple(workout_days), deps)
        return "subscription-result"

    monkeypatch.setattr(CoachAgent, "generate_subscription", staticmethod(fake_generate))
    ctx = {"prompt": "p", "period": "1m", "workout_days": ["mon"], "deps": "d"}
    result = await DISPATCH[CoachMode.subscription](ctx)
    assert result == "subscription-result"
    assert captured["args"] == ("p", "1m", ("mon",), "d")


@pytest.mark.asyncio
async def test_update_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, tuple] = {}

    async def fake_update(prompt: str, expected_workout: str, feedback: str, deps: object) -> str:
        captured["args"] = (prompt, expected_workout, feedback, deps)
        return "update-result"

    monkeypatch.setattr(CoachAgent, "update_program", staticmethod(fake_update))
    ctx = {"prompt": "p", "expected_workout": "ew", "feedback": "fb", "deps": "d"}
    result = await DISPATCH[CoachMode.update](ctx)
    assert result == "update-result"
    assert captured["args"] == ("p", "ew", "fb", "d")


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
