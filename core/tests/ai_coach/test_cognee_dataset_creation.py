import asyncio
from hashlib import md5, sha256
from pathlib import Path
from types import SimpleNamespace

from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
import ai_coach.agent.knowledge.knowledge_base as coach


def test_update_dataset_ensures_exists(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def ensure(cls, name: str, user: object) -> None:  # type: ignore[override]
        calls.append(("ensure", name))

    async def fake_add(
        text: str,
        *,
        dataset_name: str,
        user: object,
        node_set: list[str] | None,
    ) -> SimpleNamespace:
        calls.append(("add", dataset_name))
        return SimpleNamespace(dataset_id=dataset_name)

    monkeypatch.setattr(KnowledgeBase, "_ensure_dataset_exists", classmethod(ensure))
    monkeypatch.setattr(coach, "_safe_add", fake_add)

    async def runner() -> None:
        ds, created = await KnowledgeBase.update_dataset("x", "ds", user=None)
        assert (ds, created) == ("ds", True)

    asyncio.run(runner())
    assert calls == [("ensure", "ds"), ("add", "ds")]


def test_update_dataset_creates_storage_before_hashstore(monkeypatch, tmp_path):
    events: list[tuple[str, str]] = []
    created_metadata: dict[str, str] = {}
    contains_calls = {"count": 0}

    async def ensure(cls, name: str, user: object) -> None:  # type: ignore[override]
        events.append(("ensure", name))

    async def fake_contains(cls, dataset: str, digest: str) -> bool:  # type: ignore[override]
        events.append(("contains", digest))
        contains_calls["count"] += 1
        return contains_calls["count"] > 1

    async def fake_add_entry(
        text: str,
        *,
        dataset_name: str,
        user: object,
        node_set: list[str] | None,
    ) -> SimpleNamespace:
        events.append(("safe_add", dataset_name))
        return SimpleNamespace(dataset_id=dataset_name)

    async def fake_hash_add(cls, dataset: str, digest: str, metadata: dict[str, str] | None = None) -> None:  # type: ignore[override]
        events.append(("hash_add", digest))
        if metadata:
            created_metadata.update(metadata)

    original_storage_file = KnowledgeBase._ensure_storage_file.__func__

    def fake_storage_root(cls) -> Path:  # type: ignore[override]
        return tmp_path

    def tracking_storage_file(
        cls,
        digest_md5: str,
        text: str,
        *,
        dataset: str | None = None,
    ) -> tuple[Path, bool]:  # type: ignore[override]
        events.append(("storage", digest_md5))
        return original_storage_file(cls, digest_md5, text, dataset=dataset)

    monkeypatch.setattr(KnowledgeBase, "_ensure_dataset_exists", classmethod(ensure))
    monkeypatch.setattr(KnowledgeBase, "_storage_root", classmethod(fake_storage_root))
    monkeypatch.setattr(KnowledgeBase, "_ensure_storage_file", classmethod(tracking_storage_file))
    monkeypatch.setattr(coach, "_safe_add", fake_add_entry)
    monkeypatch.setattr(coach.HashStore, "contains", classmethod(fake_contains))
    monkeypatch.setattr(coach.HashStore, "add", classmethod(fake_hash_add))

    async def runner() -> None:
        dataset, created = await KnowledgeBase.update_dataset("Sample text", "kb_client_1", user=None)
        assert dataset == "kb_client_1"
        assert created is True

    asyncio.run(runner())

    expected_sha = sha256("Sample text".encode("utf-8")).hexdigest()
    expected_md5 = md5("Sample text".encode("utf-8")).hexdigest()
    stored_file = tmp_path / f"text_{expected_md5}.txt"

    assert stored_file.exists()
    assert stored_file.read_text(encoding="utf-8") == "Sample text"
    assert events[0][0] == "ensure"
    assert any(event[0] == "storage" for event in events), f"Events order mismatch: {events}"
    assert events.index(("storage", expected_md5)) < events.index(("contains", expected_sha))
    assert created_metadata["digest_sha"] == expected_sha
    assert created_metadata["digest_md5"] == expected_md5
    assert created_metadata["dataset"] == "kb_client_1"
