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

import pytest  # pyrefly: ignore[import-error]
from pydantic_ai.settings import ModelSettings

from ai_coach.agent import (
    AgentDeps,
    CoachAgent,
    ProgramAdapter,
    QAResponse,
)
from ai_coach.schemas import AICoachRequest, ProgramPayload, SubscriptionPayload
from ai_coach.types import CoachMode
from ai_coach.application import app
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from core.enums import CoachType


def _sample_program(**kwargs) -> ProgramPayload:
    day = {"day": "day1", "exercises": [{"name": "Squat", "sets": "3", "reps": "10"}]}
    base = {
        "id": 1,
        "client_profile": 1,
        "exercises_by_day": [day],
        "created_at": 0,
        "split_number": 1,
        "coach_type": "human",
    }
    base.update(kwargs)
    return ProgramPayload(**base)


def test_adapter_drops_schema_version() -> None:
    payload = _sample_program(schema_version="v1")
    program = ProgramAdapter.to_domain(payload)
    dumped = program.model_dump()
    assert "schema_version" not in dumped


def test_enum_mapping_to_coach_type() -> None:
    payload = _sample_program(coach_type="ai")
    program = ProgramAdapter.to_domain(payload)
    assert program.coach_type is CoachType.ai


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
    req = AICoachRequest(client_id=1, prompt="hi", mode="ask_ai")
    assert req.mode is CoachMode.ask_ai


@pytest.mark.asyncio
async def test_answer_question(monkeypatch) -> None:
    class DummyAgent:
        async def run(
            self,
            prompt: str,
            deps: AgentDeps,
            output_type: type[QAResponse] | None = None,
            model_settings: ModelSettings | None = None,
            message_history: list | None = None,
        ) -> QAResponse:  # pragma: no cover - dummy
            assert "MODE: ask_ai" in prompt
            assert output_type is QAResponse
            assert model_settings is not None
            return QAResponse(answer="answer", sources=["s"])

    monkeypatch.setattr(CoachAgent, "_get_agent", classmethod(lambda cls: DummyAgent()))
    deps = AgentDeps(client_id=1, locale="en", allow_save=False)
    result = await CoachAgent.answer_question("question", deps)
    assert result.answer == "answer"


def test_ask_ai_legacy(monkeypatch) -> None:
    async def fake_search(prompt: str, client_id: int) -> list[str]:
        return ["legacy"]

    async def noop(*args, **kwargs) -> None:
        return None

    async def boom(prompt: str, deps: AgentDeps) -> QAResponse:
        raise RuntimeError("boom")

    monkeypatch.setattr(CoachAgent, "answer_question", staticmethod(boom))
    monkeypatch.setattr(KnowledgeBase, "search", staticmethod(fake_search))
    monkeypatch.setattr(KnowledgeBase, "save_client_message", staticmethod(noop))
    monkeypatch.setattr(KnowledgeBase, "save_ai_message", staticmethod(noop))

    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        resp = client.post("/ask/", json={"client_id": 1, "prompt": "hi", "mode": "ask_ai"})
    assert resp.status_code == 200
    assert resp.json() == ["legacy"]
