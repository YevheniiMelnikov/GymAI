import asyncio
from typing import Any
from types import SimpleNamespace

import pytest

import ai_coach.agent.knowledge.knowledge_base as knowledge_base_module
from ai_coach.agent.coach import CoachAgent
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from core.schemas import Client
from core.schemas import QAResponse


def test_dataset_name_is_alias() -> None:
    dataset_id = KnowledgeBase._dataset_name(42)
    assert dataset_id == "kb_client_42"
    assert dataset_id == KnowledgeBase._dataset_name(42)


def test_resolve_dataset_alias_supports_legacy_prefix() -> None:
    resolved = KnowledgeBase._resolve_dataset_alias("client_7")
    assert resolved == KnowledgeBase._dataset_name(7)
    kb_alias = KnowledgeBase._resolve_dataset_alias("kb_client_9")
    assert kb_alias == "kb_client_9"


def test_normalize_output_handles_agent_result() -> None:
    qa = QAResponse(answer="ok")
    wrapped = SimpleNamespace(output=qa)
    result = CoachAgent._normalize_output(wrapped, QAResponse)
    assert result is qa


def test_normalize_output_builds_model_from_mapping() -> None:
    data = {"answer": "text"}
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


def test_debug_snapshot_compiles_dataset_information(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_list_dataset_entries(cls, dataset: str, user: Any | None) -> list[str]:
        return [f"entry:{dataset}"]

    async def fake_metadata(cls, dataset: str, user: Any | None) -> Any:
        return SimpleNamespace(id=f"id-{dataset}", updated_at="2024-10-19T12:00:00Z")

    async def fake_projection(cls, dataset: str, user_ns: Any | None) -> bool:
        return dataset.endswith("global")

    async def fake_get_user() -> Any | None:
        return SimpleNamespace(id="user-1")

    monkeypatch.setattr(KnowledgeBase, "_list_dataset_entries", classmethod(fake_list_dataset_entries))
    monkeypatch.setattr(KnowledgeBase, "_get_dataset_metadata", classmethod(fake_metadata))
    monkeypatch.setattr(KnowledgeBase, "_is_projection_ready", classmethod(fake_projection))
    monkeypatch.setattr(KnowledgeBase, "_get_cognee_user", classmethod(fake_get_user))

    snapshot = asyncio.run(KnowledgeBase.debug_snapshot(client_id=3))

    assert "datasets" in snapshot
    assert len(snapshot["datasets"]) == 2
    aliases = {item["alias"] for item in snapshot["datasets"]}
    assert aliases == {"kb_client_3", KnowledgeBase.GLOBAL_DATASET}
    for item in snapshot["datasets"]:
        assert item["documents"] == 1
        assert item["id"].startswith("id-")
