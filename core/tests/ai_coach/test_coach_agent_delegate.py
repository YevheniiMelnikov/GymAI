import asyncio

import pytest

from ai_coach.agent.coach import CoachAgent


class _DummyHelper:
    calls: list[str] = []
    agent: str | object = "agent"

    @classmethod
    def _get_agent(cls) -> str:
        cls.calls.append("agent")
        return str(cls.agent)

    @classmethod
    def _language_context(cls, deps: object) -> tuple[str, str]:
        cls.calls.append("language_context")
        return ("en", "English (en)")

    @classmethod
    def _complete_with_retries(cls, *args: object, **kwargs: object) -> str:
        cls.calls.append("complete")
        return "complete"

    @staticmethod
    async def _message_history(profile_id: int) -> list[str]:
        _DummyHelper.calls.append(f"history:{profile_id}")
        return ["hi"]

    @staticmethod
    def _normalize_text(text: str | None) -> str:
        _DummyHelper.calls.append("normalize")
        return (text or "").strip()


def test_coach_agent_delegates_classmethods(monkeypatch: pytest.MonkeyPatch) -> None:
    _DummyHelper.calls.clear()
    monkeypatch.setattr(CoachAgent, "llm_helper", _DummyHelper)
    monkeypatch.setattr(
        CoachAgent,
        "_get_agent",
        classmethod(lambda cls: cls.llm_helper._get_agent()),
    )
    monkeypatch.setattr(
        CoachAgent,
        "_language_context",
        classmethod(lambda cls, deps: cls.llm_helper._language_context(deps)),
    )
    monkeypatch.setattr(
        CoachAgent,
        "_complete_with_retries",
        classmethod(lambda cls, *a, **k: cls.llm_helper._complete_with_retries(*a, **k)),
    )

    assert CoachAgent._get_agent() == "agent"  # type: ignore[comparison-overlap]
    assert CoachAgent._language_context(object())[0] == "en"
    assert CoachAgent._complete_with_retries(object(), "", "", [], profile_id=1, max_tokens=1) == "complete"
    assert "agent" in _DummyHelper.calls
    assert "language_context" in _DummyHelper.calls
    assert "complete" in _DummyHelper.calls


async def _call_history() -> list[str]:
    return await CoachAgent._message_history(5)


def test_coach_agent_delegates_staticmethods(monkeypatch: pytest.MonkeyPatch) -> None:
    _DummyHelper.calls.clear()
    monkeypatch.setattr(CoachAgent, "llm_helper", _DummyHelper)

    assert CoachAgent._normalize_text(" test ") == "test"
    assert asyncio.run(_call_history()) == ["hi"]
    assert "normalize" in _DummyHelper.calls
    assert "history:5" in _DummyHelper.calls
