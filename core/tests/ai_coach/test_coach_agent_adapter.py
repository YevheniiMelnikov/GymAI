import os

os.environ.setdefault("SECRET_KEY", "x")
os.environ.setdefault("API_KEY", "x")
os.environ.setdefault("BOT_TOKEN", "x")
os.environ.setdefault("BOT_LINK", "x")
os.environ.setdefault("WEBHOOK_HOST", "x")
os.environ.setdefault("SPREADSHEET_ID", "x")
os.environ.setdefault("TG_SUPPORT_CONTACT", "x")
os.environ.setdefault("PUBLIC_OFFER", "x")
os.environ.setdefault("PRIVACY_POLICY", "x")
os.environ.setdefault("EMAIL", "x")
os.environ.setdefault("ADMIN_ID", "1")

import json
from types import SimpleNamespace
from typing import Any, Sequence

import pytest  # pyrefly: ignore[import-error]

from ai_coach.agent import AgentDeps, CoachAgent, ProgramAdapter, QAResponse
from ai_coach.exceptions import AgentExecutionAborted
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase, KnowledgeSnippet
from ai_coach.schemas import AICoachRequest, ProgramPayload, SubscriptionPayload
from ai_coach.types import CoachMode
from ai_coach.application import app
from ai_coach.api import dedupe_cache


@pytest.fixture(autouse=True)
def _reset_completion_client() -> Any:
    CoachAgent._completion_client = None
    CoachAgent._completion_model_name = None
    yield
    CoachAgent._completion_client = None
    CoachAgent._completion_model_name = None


def _dummy_completion_client() -> tuple[Any, str]:
    completions = SimpleNamespace(create=lambda *args, **kwargs: None)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, "dummy-model"


def _sample_program(**kwargs) -> ProgramPayload:
    day = {"day": "day1", "exercises": [{"name": "Squat", "sets": "3", "reps": "10"}]}
    base = {
        "id": 1,
        "profile": 1,
        "exercises_by_day": [day],
        "created_at": 0,
        "split_number": 1,
    }
    base.update(kwargs)
    return ProgramPayload(**base)


def test_adapter_drops_schema_version() -> None:
    payload = _sample_program(schema_version="v1")
    program = ProgramAdapter.to_domain(payload)
    dumped = program.model_dump()
    assert "schema_version" not in dumped


def test_split_number_defaults() -> None:
    payload = _sample_program(split_number=None)
    program = ProgramAdapter.to_domain(payload)
    assert program.split_number == len(program.exercises_by_day)


def test_payload_split_number_defaults() -> None:
    payload = _sample_program(split_number=None)
    assert payload.split_number == len(payload.exercises_by_day)


def test_payload_empty_days_validation() -> None:
    with pytest.raises(ValueError):
        _sample_program(exercises_by_day=[])


def test_payload_missing_fields_validation() -> None:
    bad_day = {"day": "d", "exercises": [{"sets": "3", "reps": "10"}]}
    with pytest.raises(ValueError):
        _sample_program(exercises_by_day=[bad_day])


def test_subscription_payload_validation() -> None:
    with pytest.raises(ValueError):
        SubscriptionPayload(workout_days=[], exercises=[])
    day = {"day": "d", "exercises": [{"name": "x", "sets": "1", "reps": "1"}]}
    payload = SubscriptionPayload(workout_days=["mon"], exercises=[day])
    assert payload.workout_days == ["mon"]


def test_ask_request_accepts_ask_ai() -> None:
    req = AICoachRequest(profile_id=1, prompt="hi", mode="ask_ai")
    assert req.mode is CoachMode.ask_ai


@pytest.mark.asyncio
async def test_answer_question_uses_primary_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    class SuccessAgent:
        async def run(self, *args: Any, **kwargs: Any) -> QAResponse:
            return QAResponse(answer="Final", sources=["kb_global"])

    monkeypatch.setattr(CoachAgent, "_get_agent", classmethod(lambda cls: SuccessAgent()))
    deps = AgentDeps(profile_id=7, locale="en", allow_save=False)
    result = await CoachAgent.answer_question("question", deps)
    assert result.answer == "Final"
    assert result.sources == ["kb_global"]


@pytest.mark.asyncio
async def test_answer_question_uses_fallback_when_completion_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fallback(
        cls,
        prompt: str,
        deps: AgentDeps,
        history: list[object],
        *,
        prefetched_knowledge: Sequence[KnowledgeSnippet] | None = None,
    ) -> QAResponse | None:
        return QAResponse(answer="Fallback", sources=["kb_global"])

    class AbortingAgent:
        async def run(self, *args: Any, **kwargs: Any) -> QAResponse:
            raise AgentExecutionAborted("kb empty", reason="knowledge_base_empty")

    monkeypatch.setattr(CoachAgent, "_get_agent", classmethod(lambda cls: AbortingAgent()))
    monkeypatch.setattr(CoachAgent, "_fallback_answer_question", classmethod(fake_fallback))
    deps = AgentDeps(profile_id=9, locale="en", allow_save=False)
    result = await CoachAgent.answer_question("question", deps)
    assert result.answer == "Fallback"
    assert result.sources == ["kb_global"]


@pytest.mark.asyncio
async def test_answer_question_manual_answer_when_everything_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fallback(
        cls,
        prompt: str,
        deps: AgentDeps,
        history: list[object],
        *,
        prefetched_knowledge: Sequence[KnowledgeSnippet] | None = None,
    ) -> QAResponse | None:
        return None

    class AbortingAgent:
        async def run(self, *args: Any, **kwargs: Any) -> QAResponse:
            raise AgentExecutionAborted("kb empty", reason="knowledge_base_empty")

    monkeypatch.setattr(CoachAgent, "_get_agent", classmethod(lambda cls: AbortingAgent()))
    monkeypatch.setattr(CoachAgent, "_fallback_answer_question", classmethod(fake_fallback))
    deps = AgentDeps(profile_id=5, locale="en", allow_save=False)
    with pytest.raises(AgentExecutionAborted) as exc_info:
        await CoachAgent.answer_question("question", deps)
    assert exc_info.value.reason == "ask_ai_unavailable"


@pytest.mark.asyncio
async def test_answer_question_handles_agent_aborted(monkeypatch: pytest.MonkeyPatch) -> None:
    class AbortingAgent:
        async def run(self, *args: Any, **kwargs: Any) -> QAResponse:
            raise AgentExecutionAborted("kb empty", reason="knowledge_base_empty")

    monkeypatch.setattr(CoachAgent, "_get_agent", classmethod(lambda cls: AbortingAgent()))
    monkeypatch.setattr(CoachAgent, "_get_completion_client", classmethod(lambda cls: _dummy_completion_client()))
    monkeypatch.setattr(CoachAgent, "_ensure_llm_logging", classmethod(lambda cls, target, model_id=None: None))
    deps = AgentDeps(profile_id=11, locale="en", allow_save=False)
    with pytest.raises(AgentExecutionAborted) as exc_info:
        await CoachAgent.answer_question("question", deps)
    assert exc_info.value.reason == "ask_ai_unavailable"


def test_extract_choice_content_tool_arguments() -> None:
    arguments = json.dumps({"answer": "Yes", "sources": ["doc"]})
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="",
                    tool_calls=[SimpleNamespace(function=SimpleNamespace(arguments=arguments))],
                ),
                finish_reason="stop",
            )
        ]
    )
    extracted = CoachAgent._extract_choice_content(response, profile_id=42)
    assert "answer" in extracted


def test_normalize_tool_call_arguments_fills_sources() -> None:
    payload = {"answer": "Ok", "sources": ["  doc "]}
    text = CoachAgent._normalize_tool_call_arguments(payload)
    data = json.loads(text)
    assert data["sources"] == ["doc"]


def test_api_passthrough_returns_llm_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_answer(prompt: str, deps: AgentDeps) -> QAResponse:
        return QAResponse(answer="OK_FROM_LLM", sources=["kb_global"])

    monkeypatch.setattr(CoachAgent, "answer_question", staticmethod(fake_answer))

    async def fake_save(*args: Any, **kwargs: Any) -> None:
        pass

    monkeypatch.setattr(KnowledgeBase, "save_client_message", fake_save)
    monkeypatch.setattr(KnowledgeBase, "save_ai_message", fake_save)

    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        resp = client.post("/ask/", json={"profile_id": 1, "prompt": "hi", "mode": "ask_ai"})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["answer"] == "OK_FROM_LLM"
    assert payload["sources"] == ["kb_global"]


def test_ask_ai_runtime_error(monkeypatch) -> None:
    async def boom(prompt: str, deps: AgentDeps) -> QAResponse:
        raise RuntimeError("boom")

    monkeypatch.setattr(CoachAgent, "answer_question", staticmethod(boom))
    dedupe_cache.clear()

    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        resp = client.post("/ask/", json={"profile_id": 1, "prompt": "hi", "mode": "ask_ai"})
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Service unavailable"
