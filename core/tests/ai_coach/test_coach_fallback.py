from types import SimpleNamespace
from typing import Any

import pytest

from ai_coach.agent.base import AgentDeps
from ai_coach.agent.coach import CoachAgent
from ai_coach.agent.knowledge.knowledge_base import KnowledgeSnippet
from config.app_settings import settings


class _FakeMessage(SimpleNamespace):
    pass


class _FakeResponse(SimpleNamespace):
    pass


def _empty_response() -> Any:
    choice = SimpleNamespace(message=_FakeMessage(content=""), finish_reason="length")
    usage = SimpleNamespace(prompt_tokens=200, completion_tokens=0, total_tokens=200)
    return _FakeResponse(choices=[choice], usage=usage)


def _text_response(payload: str, *, finish_reason: str = "stop") -> Any:
    choice = SimpleNamespace(message=_FakeMessage(content=payload), finish_reason=finish_reason)
    usage = SimpleNamespace(prompt_tokens=180, completion_tokens=120, total_tokens=300)
    return _FakeResponse(choices=[choice], usage=usage)


@pytest.mark.asyncio
async def test_fallback_summary_on_empty_completions(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    async def fake_call_llm(
        client: Any,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str,
        max_tokens: int,
    ) -> Any:
        calls["count"] += 1
        return _empty_response()

    def fake_parse(
        cls,
        content: str,
        entry_ids: list[str],
        *,
        profile_id: int,
    ) -> tuple[str, list[str]]:
        return content, entry_ids

    helper = CoachAgent.llm_helper
    monkeypatch.setattr(helper, "call_llm", staticmethod(fake_call_llm))
    monkeypatch.setattr(helper, "_parse_fallback_content", classmethod(fake_parse))
    monkeypatch.setattr(CoachAgent, "get_completion_client", classmethod(lambda cls: (object(), settings.AGENT_MODEL)))
    monkeypatch.setattr(helper, "_ensure_llm_logging", classmethod(lambda cls, *args, **kwargs: None))

    deps = AgentDeps(profile_id=1, locale="uk")
    knowledge = [
        KnowledgeSnippet(text="План включає силові тренування тричі на тиждень.", dataset="kb_profile_1"),
        KnowledgeSnippet(text="Додавай розтяжку для відновлення.", dataset="kb_global"),
    ]

    result = await CoachAgent._fallback_answer_question(
        "Що робити, щоб прогресувати?",
        deps,
        history=[],
        profile_context="",
        prefetched_knowledge=knowledge,
    )

    assert result is not None
    assert "Ось" in result.answer
    assert result.sources
    assert calls["count"] >= 1


@pytest.mark.asyncio
async def test_complete_with_retries_returns_second_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    async def fake_call_llm(
        client: Any,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str,
        max_tokens: int,
    ) -> Any:
        calls["count"] += 1
        if calls["count"] == 1:
            return _empty_response()
        return _text_response("Фінальна відповідь")

    def fake_parse(
        cls,
        content: str,
        entry_ids: list[str],
        *,
        profile_id: int,
    ) -> tuple[str, list[str]]:
        return content, entry_ids

    helper = CoachAgent.llm_helper
    monkeypatch.setattr(helper, "call_llm", staticmethod(fake_call_llm))
    monkeypatch.setattr(helper, "_parse_fallback_content", classmethod(fake_parse))

    result = await CoachAgent._complete_with_retries(
        client=object(),
        system_prompt="system",
        user_prompt="user prompt",
        entry_ids=["KB-1"],
        profile_id=1,
        max_tokens=settings.AI_COACH_FIRST_PASS_MAX_TOKENS,
        model=settings.AGENT_MODEL,
    )

    assert result is not None
    assert result.answer == "Фінальна відповідь"
    assert result.sources == ["KB-1"]
    assert calls["count"] == 2


def test_extract_choice_content_handles_text_key() -> None:
    response = _FakeResponse(choices=[{"text": "Прямо зазначений текст", "finish_reason": "stop"}])
    content = CoachAgent._extract_choice_content(response, profile_id=7)
    assert content == "Прямо зазначений текст"


def test_extract_choice_content_variants() -> None:
    responses = [
        _FakeResponse(choices=[SimpleNamespace(message=_FakeMessage(content="Повідомлення"), finish_reason="stop")]),
        _FakeResponse(choices=[{"content": "Текст у choice", "finish_reason": "stop"}]),
        _FakeResponse(
            choices=[
                {
                    "message": {
                        "content": [
                            {"text": "Частина 1"},
                            {"text": "Частина 2"},
                        ]
                    },
                    "finish_reason": "stop",
                }
            ]
        ),
    ]
    extracted = [CoachAgent._extract_choice_content(response, profile_id=5) for response in responses]
    assert extracted[0] == "Повідомлення"
    assert extracted[1] == "Текст у choice"
    assert extracted[2] == "Частина 1\nЧастина 2"


@pytest.mark.asyncio
async def test_complete_with_retries_length_with_content(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    async def fake_call_llm(
        client: Any,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str,
        max_tokens: int,
    ) -> Any:
        calls["count"] += 1
        return _text_response("Розгорнута відповідь", finish_reason="length")

    def fake_parse(
        cls,
        content: str,
        entry_ids: list[str],
        *,
        profile_id: int,
    ) -> tuple[str, list[str]]:
        return content, entry_ids

    helper = CoachAgent.llm_helper
    monkeypatch.setattr(helper, "call_llm", staticmethod(fake_call_llm))
    monkeypatch.setattr(helper, "_parse_fallback_content", classmethod(fake_parse))

    result = await CoachAgent._complete_with_retries(
        client=object(),
        system_prompt="system",
        user_prompt="user prompt",
        entry_ids=["KB-1"],
        profile_id=3,
        max_tokens=settings.AI_COACH_FIRST_PASS_MAX_TOKENS,
        model=settings.AGENT_MODEL,
    )

    assert result is not None
    assert result.answer == "Розгорнута відповідь"
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_complete_with_retries_stops_after_two_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    async def fake_call_llm(
        client: Any,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str,
        max_tokens: int,
    ) -> Any:
        calls["count"] += 1
        return _empty_response()

    def fake_parse(
        cls,
        content: str,
        entry_ids: list[str],
        *,
        profile_id: int,
    ) -> tuple[str, list[str]]:
        return "", []

    helper = CoachAgent.llm_helper
    monkeypatch.setattr(helper, "call_llm", staticmethod(fake_call_llm))
    monkeypatch.setattr(helper, "_parse_fallback_content", classmethod(fake_parse))

    result = await CoachAgent._complete_with_retries(
        client=object(),
        system_prompt="system",
        user_prompt="user prompt",
        entry_ids=["KB-1"],
        profile_id=4,
        max_tokens=settings.AI_COACH_FIRST_PASS_MAX_TOKENS,
        model=settings.AGENT_MODEL,
    )

    assert result is None
    assert calls["count"] == 2
