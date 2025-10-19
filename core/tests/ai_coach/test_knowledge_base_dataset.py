import asyncio
from typing import Any
from types import SimpleNamespace
from uuid import UUID

import pytest

import ai_coach.agent.knowledge.knowledge_base as knowledge_base_module
from ai_coach.agent.coach import CoachAgent
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from core.schemas import Client
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


def test_ensure_profile_indexed_fetches_client_by_id(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, Any] = {}

    async def fake_get_client(client_id: int) -> Client:
        recorded["client_id"] = client_id
        return Client(id=client_id, profile=42)

    async def fake_update_dataset(
        cls,
        text: str,
        dataset: str,
        user: Any,
        node_set: list[str] | None = None,
    ) -> tuple[str, bool]:
        recorded["dataset"] = dataset
        recorded["text"] = text
        recorded["node_set"] = node_set
        return dataset, True

    async def fake_process_dataset(cls, dataset: str, user: Any) -> None:
        recorded["processed"] = dataset

    monkeypatch.setattr(
        knowledge_base_module,
        "APIService",
        SimpleNamespace(profile=SimpleNamespace(get_client=fake_get_client)),
    )
    monkeypatch.setattr(KnowledgeBase, "update_dataset", classmethod(fake_update_dataset))
    monkeypatch.setattr(KnowledgeBase, "_process_dataset", classmethod(fake_process_dataset))

    client_id = 7
    asyncio.run(KnowledgeBase._ensure_profile_indexed(client_id, user=None))

    assert recorded["client_id"] == client_id
    assert recorded["dataset"] == KnowledgeBase._dataset_name(client_id)
    assert recorded["node_set"] == ["client_profile"]
    assert recorded["processed"] == KnowledgeBase._dataset_name(client_id)
    assert recorded["text"].startswith("profile: ")
