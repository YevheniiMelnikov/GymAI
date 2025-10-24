import asyncio
from hashlib import sha256
from types import SimpleNamespace
from typing import Any, Sequence

import pytest

import ai_coach.agent.knowledge.knowledge_base as knowledge_base_module
from ai_coach.agent.coach import CoachAgent
from ai_coach.agent.knowledge.knowledge_base import DatasetRow, KnowledgeBase

from core.schemas import Client
from core.schemas import QAResponse


async def _fake_hash_add(cls, dataset: str, digest: str, metadata: dict[str, Any] | None = None) -> None:
    return None


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
        metadata: Any | None = None,
    ) -> tuple[str, bool]:
        recorded["dataset"] = dataset
        recorded["text"] = text
        recorded["node_set"] = node_set
        recorded["metadata"] = metadata
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
    assert recorded["metadata"] == {"kind": "document", "source": "client_profile"}


def test_debug_snapshot_compiles_dataset_information(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_list_dataset_entries(cls, dataset: str, user: Any | None) -> list[DatasetRow]:
        return [DatasetRow(text=f"entry:{dataset}", metadata={"kind": "document", "dataset": dataset})]

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


def test_build_snippets_skip_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_collect_metadata(digest: str, datasets: Sequence[str]) -> tuple[str | None, dict[str, Any] | None]:
        if digest == sha256("message".encode()).hexdigest():
            return datasets[0], {"kind": "message"}
        if digest == sha256("note".encode()).hexdigest():
            return datasets[0], {"kind": "note"}
        return datasets[0], {"kind": "document"}

    async def fake_contains(dataset: str, digest: str) -> bool:
        return True

    monkeypatch.setattr(KnowledgeBase, "_collect_metadata", classmethod(fake_collect_metadata))
    monkeypatch.setattr(
        knowledge_base_module.HashStore,
        "contains",
        classmethod(fake_contains),
    )
    monkeypatch.setattr(
        knowledge_base_module.HashStore,
        "add",
        classmethod(_fake_hash_add),
    )
    snippets = asyncio.run(KnowledgeBase._build_snippets(["document", "message", "note"], ["ds"], user=None))
    texts = [item.text for item in snippets]
    kinds = [item.kind for item in snippets]
    assert texts == ["document", "note"]
    assert kinds == ["document", "note"]


def test_fallback_entries_skip_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_list_dataset_entries(cls, dataset: str, user: Any | None) -> list[DatasetRow]:
        return [
            DatasetRow(text=" document ", metadata={"kind": "document", "dataset": dataset}),
            DatasetRow(text="client: hi", metadata={"kind": "message", "role": "client", "dataset": dataset}),
        ]

    monkeypatch.setattr(KnowledgeBase, "_list_dataset_entries", classmethod(fake_list_dataset_entries))
    monkeypatch.setattr(
        knowledge_base_module.HashStore,
        "add",
        classmethod(_fake_hash_add),
    )

    results = asyncio.run(KnowledgeBase._fallback_dataset_entries(["ds"], user=None, top_k=5))
    assert results == ["document"]


def test_build_snippets_skip_unindexed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_collect_metadata(digest: str, datasets: Sequence[str]) -> tuple[str | None, dict[str, Any] | None]:
        return datasets[0], None

    async def fake_contains(dataset: str, digest: str) -> bool:
        return digest == sha256("kept".encode()).hexdigest()

    monkeypatch.setattr(KnowledgeBase, "_collect_metadata", classmethod(fake_collect_metadata))
    monkeypatch.setattr(
        knowledge_base_module.HashStore,
        "contains",
        classmethod(fake_contains),
    )
    monkeypatch.setattr(
        knowledge_base_module.HashStore,
        "add",
        classmethod(_fake_hash_add),
    )

    snippets = asyncio.run(KnowledgeBase._build_snippets(["kept", "ignored"], ["ds"], user=None))
    assert [item.text for item in snippets] == ["kept", "ignored"]


def test_build_knowledge_entries_skip_non_content() -> None:
    snippet_doc = knowledge_base_module.KnowledgeSnippet(text=" doc ")
    snippet_unknown = knowledge_base_module.KnowledgeSnippet(text="ignored", kind="unknown")
    ids, entries = CoachAgent._build_knowledge_entries([snippet_doc, snippet_unknown, " other "])
    assert ids == ["KB-1", "KB-2"]
    assert entries == ["doc", "other"]
