from uuid import UUID
from types import SimpleNamespace

from ai_coach.agent.coach import CoachAgent
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from core.schemas import QAResponse


def test_dataset_name_is_uuid() -> None:
    dataset_id = KnowledgeBase._dataset_name(42)
    parsed = UUID(dataset_id)
    assert parsed.version == 5
    assert dataset_id == KnowledgeBase._dataset_name(42)


def test_resolve_dataset_alias_supports_legacy_prefix() -> None:
    resolved = KnowledgeBase._resolve_dataset_alias("client_7")
    assert resolved == KnowledgeBase._dataset_name(7)


def test_normalize_output_handles_agent_result() -> None:
    qa = QAResponse(answer="ok", sources=["doc"])
    wrapped = SimpleNamespace(output=qa)
    result = CoachAgent._normalize_output(wrapped, QAResponse)
    assert result is qa


def test_normalize_output_builds_model_from_mapping() -> None:
    data = {"answer": "text", "sources": ["ref"]}
    result = CoachAgent._normalize_output(data, QAResponse)
    assert isinstance(result, QAResponse)
    assert result.answer == "text"
