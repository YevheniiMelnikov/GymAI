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


def _text_response(payload: str) -> Any:
    choice = SimpleNamespace(message=_FakeMessage(content=payload), finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=180, completion_tokens=120, total_tokens=300)
    return _FakeResponse(choices=[choice], usage=usage)


@pytest.mark.asyncio
async def test_fallback_summary_on_empty_completions(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    async def fake_run_completion(
        cls,
        client: Any,
        system_prompt: str,
        user_prompt: str,
        *,
        use_json: bool,
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
        expects_json: bool,
        client_id: int,
    ) -> tuple[str, list[str]]:
        return content, entry_ids

    monkeypatch.setattr(CoachAgent, "_run_completion", classmethod(fake_run_completion))
    monkeypatch.setattr(CoachAgent, "_parse_fallback_content", classmethod(fake_parse))
    monkeypatch.setattr(CoachAgent, "_get_completion_client", classmethod(lambda cls: (object(), settings.AGENT_MODEL)))
    monkeypatch.setattr(CoachAgent, "_ensure_llm_logging", classmethod(lambda cls, *a, **k: None))

    deps = AgentDeps(client_id=1, locale="uk")
    knowledge = [
        KnowledgeSnippet(text="План включає силові тренування тричі на тиждень.", dataset="kb_client_1"),
        KnowledgeSnippet(text="Додавай розтяжку для відновлення.", dataset="kb_global"),
    ]

    result = await CoachAgent._fallback_answer_question(
        "Що робити, щоб прогресувати?",
        deps,
        history=[],
        prefetched_knowledge=knowledge,
    )

    assert result is not None
    assert "Ось" in result.answer
    assert result.sources
    assert calls["count"] >= 1


@pytest.mark.asyncio
async def test_complete_with_retries_returns_second_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    async def fake_run_completion(
        cls,
        client: Any,
        system_prompt: str,
        user_prompt: str,
        *,
        use_json: bool,
        model: str,
        max_tokens: int,
    ) -> Any:
        if calls["count"] == 0:
            calls["count"] += 1
            return _empty_response()
        return _text_response("Фінальна відповідь")

    def fake_parse(
        cls,
        content: str,
        entry_ids: list[str],
        *,
        expects_json: bool,
        client_id: int,
    ) -> tuple[str, list[str]]:
        return content, entry_ids

    monkeypatch.setattr(CoachAgent, "_run_completion", classmethod(fake_run_completion))
    monkeypatch.setattr(CoachAgent, "_parse_fallback_content", classmethod(fake_parse))

    result = await CoachAgent._complete_with_retries(
        client=object(),
        system_prompt="system",
        user_prompt="user prompt",
        entry_ids=["KB-1"],
        supports_json=False,
        client_id=1,
        max_tokens=settings.AI_COACH_FIRST_PASS_MAX_TOKENS,
    )

    assert result is not None
    assert result.answer == "Фінальна відповідь"
    assert result.sources == ["KB-1"]


def test_extract_choice_content_handles_text_key() -> None:
    response = _FakeResponse(choices=[{"text": "Прямо зазначений текст", "finish_reason": "stop"}])
    content = CoachAgent._extract_choice_content(response, client_id=7)
    assert content == "Прямо зазначений текст"
