import asyncio
from dataclasses import dataclass
from hashlib import md5, sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence
from uuid import UUID

import pytest

import ai_coach.agent.knowledge.knowledge_base as knowledge_base_module
from ai_coach.agent.coach import CoachAgent
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from ai_coach.agent.knowledge.schemas import (
    DatasetRow,
    KnowledgeSnippet,
    ProjectionStatus,
)
from core.schemas import Profile, QAResponse


async def _fake_hash_add(cls, dataset: str, digest: str, metadata: dict[str, Any] | None = None) -> None:
    return None


def test_dataset_name_is_alias() -> None:
    dataset_id = KnowledgeBase._dataset_name(42)
    assert dataset_id == "kb_profile_42"
    assert dataset_id == KnowledgeBase._dataset_name(42)


def test_resolve_dataset_alias_supports_legacy_prefix() -> None:
    resolved = KnowledgeBase._resolve_dataset_alias("client_7")
    assert resolved == KnowledgeBase._dataset_name(7)
    kb_alias = KnowledgeBase._resolve_dataset_alias("kb_profile_9")
    assert kb_alias == "kb_profile_9"


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


def test_ensure_profile_indexed_fetches_profile_by_id(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, Any] = {}

    async def fake_get_profile(profile_id: int) -> Profile:
        recorded["profile_id"] = profile_id
        return Profile(id=profile_id, tg_id=profile_id, language="en")

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
        normalized = KnowledgeBase._normalize_text(text)
        digest_sha = sha256(normalized.encode("utf-8")).hexdigest()
        digest_md5 = md5(normalized.encode("utf-8")).hexdigest()
        payload = dict(metadata or {})
        payload.setdefault("dataset", dataset)
        payload.setdefault("digest_sha", digest_sha)
        payload.setdefault("digest_md5", digest_md5)
        recorded["metadata"] = payload
        return dataset, True

    async def fake_process_dataset(cls, dataset: str, user: Any) -> None:
        recorded["processed"] = dataset

    monkeypatch.setattr(
        knowledge_base_module,
        "APIService",
        SimpleNamespace(profile=SimpleNamespace(get_profile=fake_get_profile)),
    )
    monkeypatch.setattr(KnowledgeBase, "update_dataset", classmethod(fake_update_dataset))
    monkeypatch.setattr(KnowledgeBase, "_process_dataset", classmethod(fake_process_dataset))

    profile_id = 7
    asyncio.run(KnowledgeBase._ensure_profile_indexed(profile_id, user=None))

    assert recorded["profile_id"] == profile_id
    assert recorded["dataset"] == KnowledgeBase._dataset_name(profile_id)
    assert recorded["node_set"] == ["profile"]
    assert recorded["processed"] == KnowledgeBase._dataset_name(profile_id)
    assert recorded["text"].startswith("profile: ")
    assert recorded["metadata"]["kind"] == "document"
    assert recorded["metadata"]["source"] == "profile"
    assert recorded["metadata"]["dataset"] == KnowledgeBase._dataset_name(profile_id)


def test_debug_snapshot_compiles_dataset_information(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_list_dataset_entries(cls, dataset: str, user: Any | None) -> list[DatasetRow]:
        return [DatasetRow(text=f"entry:{dataset}", metadata={"kind": "document", "dataset": dataset})]

    async def fake_metadata(cls, dataset: str, user: Any | None) -> Any:
        return SimpleNamespace(id=f"id-{dataset}", updated_at="2024-10-19T12:00:00Z")

    async def fake_projection(cls, dataset: str, user: Any | None) -> tuple[bool, str]:
        projected = dataset.endswith("global")
        return projected, "ready" if projected else "pending"

    async def fake_get_user(cls) -> Any | None:  # type: ignore[override]
        return SimpleNamespace(id="user-1")

    monkeypatch.setattr(KnowledgeBase, "_list_dataset_entries", classmethod(fake_list_dataset_entries))
    monkeypatch.setattr(KnowledgeBase, "_get_dataset_metadata", classmethod(fake_metadata))
    monkeypatch.setattr(KnowledgeBase, "_is_projection_ready", classmethod(fake_projection))
    monkeypatch.setattr(KnowledgeBase, "_get_cognee_user", classmethod(fake_get_user))

    snapshot = asyncio.run(KnowledgeBase.debug_snapshot(profile_id=3))

    assert "datasets" in snapshot
    assert len(snapshot["datasets"]) == 2
    aliases = {item["alias"] for item in snapshot["datasets"]}
    assert aliases == {"kb_profile_3", KnowledgeBase.GLOBAL_DATASET}
    for item in snapshot["datasets"]:
        assert item["documents"] == 1
        assert item["id"].startswith("id-")


def test_build_snippets_skip_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_collect_metadata(
        cls, digest: str, datasets: Sequence[str]
    ) -> tuple[str | None, dict[str, Any] | None]:  # type: ignore[override]
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


@pytest.mark.asyncio
async def test_add_text_merges_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, Any] = {}

    async def fake_update_dataset(
        cls,
        text: str,
        dataset: str,
        user: Any,
        node_set: list[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[str, bool]:
        recorded["text"] = text
        recorded["dataset"] = dataset
        recorded["node_set"] = node_set
        normalized = KnowledgeBase._normalize_text(text)
        digest_sha = sha256(normalized.encode("utf-8")).hexdigest()
        digest_md5 = md5(normalized.encode("utf-8")).hexdigest()
        payload = dict(metadata or {})
        payload.setdefault("dataset", dataset)
        payload.setdefault("digest_sha", digest_sha)
        payload.setdefault("digest_md5", digest_md5)
        recorded["metadata"] = payload
        return dataset, True

    async def fake_process_dataset(cls, dataset: str, user: Any | None) -> None:
        recorded["processed"] = dataset

    async def fake_get_user(cls) -> Any | None:
        return SimpleNamespace(id="user-5")

    monkeypatch.setattr(KnowledgeBase, "update_dataset", classmethod(fake_update_dataset))
    monkeypatch.setattr(KnowledgeBase, "_process_dataset", classmethod(fake_process_dataset))
    monkeypatch.setattr(KnowledgeBase, "_get_cognee_user", classmethod(fake_get_user))

    await KnowledgeBase.add_text(
        "Training plan",
        dataset=KnowledgeBase.GLOBAL_DATASET,
        metadata={"kind": "document", "source": "gdrive", "title": "plan.pdf"},
    )
    assert recorded["text"] == "Training plan"
    assert recorded["dataset"] == KnowledgeBase.GLOBAL_DATASET
    assert recorded["metadata"]["kind"] == "document"
    assert recorded["metadata"]["source"] == "gdrive"
    assert recorded["metadata"]["title"] == "plan.pdf"
    assert recorded["metadata"]["dataset"] == KnowledgeBase.GLOBAL_DATASET
    assert "digest_sha" in recorded["metadata"]
    assert "digest_md5" in recorded["metadata"]
    assert recorded["processed"] == KnowledgeBase.GLOBAL_DATASET


@pytest.mark.asyncio
async def test_rebuild_from_disk_populates_hashstore_when_graph_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "cognee"
    storage_root.mkdir()
    texts = ["Document One", "Document Two"]
    aliases = ["kb_profile_1"] * len(texts)
    for text in texts:
        normalized = KnowledgeBase._normalize_text(text)
        digest_sha = sha256(normalized.encode("utf-8")).hexdigest()
        (storage_root / f"text_{digest_sha}.txt").write_text(text, encoding="utf-8")

    monkeypatch.setattr(
        KnowledgeBase,
        "_storage_root",
        classmethod(lambda cls: storage_root),
    )

    created, linked = await KnowledgeBase._rebuild_from_disk(aliases[0])

    assert created == len(texts)
    assert linked == len(texts)
    hashes = await knowledge_base_module.HashStore.list(aliases[0])
    assert len(hashes) == len(texts)
    for text in texts:
        normalized = KnowledgeBase._normalize_text(text)
        digest_sha = sha256(normalized.encode("utf-8")).hexdigest()
        assert digest_sha in hashes


@pytest.mark.asyncio
async def test_wait_for_projection_timeout_returns_timeout_status(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_ready(cls, dataset: str, user: Any | None) -> tuple[bool, str]:
        return False, "pending"

    async def fake_sleep(duration: float) -> None:
        return None

    monkeypatch.setattr(
        KnowledgeBase,
        "_is_projection_ready",
        classmethod(fake_ready),
    )
    monkeypatch.setattr(knowledge_base_module.asyncio, "sleep", fake_sleep)

    status = await KnowledgeBase._wait_for_projection("kb_global", user=None, timeout_s=0.01)
    assert status == ProjectionStatus.TIMEOUT


@pytest.mark.asyncio
async def test_wait_for_projection_timeout_skips_global_during_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_get_user(cls) -> Any | None:
        return None

    async def fake_profile_indexed(cls, profile_id: int, user: Any | None) -> None:
        return None

    async def fake_ensure_exists(cls, dataset: str, user: Any | None) -> None:
        return None

    async def fake_search_single_query(
        cls,
        query: str,
        datasets: list[str],
        user: Any | None,
        k: int | None,
        profile_id: int,
        *,
        request_id: str | None = None,
    ) -> list[KnowledgeSnippet]:
        captured["datasets"] = list(datasets)
        return []

    monkeypatch.setattr(
        KnowledgeBase,
        "ensure_global_projected",
        classmethod(lambda cls, timeout: False),
    )
    monkeypatch.setattr(KnowledgeBase, "_get_cognee_user", classmethod(fake_get_user))
    monkeypatch.setattr(KnowledgeBase, "_ensure_profile_indexed", classmethod(fake_profile_indexed))
    monkeypatch.setattr(KnowledgeBase, "_ensure_dataset_exists", classmethod(fake_ensure_exists))
    monkeypatch.setattr(KnowledgeBase, "_search_single_query", classmethod(fake_search_single_query))
    monkeypatch.setattr(
        KnowledgeBase,
        "_ensure_dataset_projected",
        classmethod(lambda cls, dataset, user, timeout=2.0: True),
    )

    await KnowledgeBase.search("routine", profile_id=99, request_id="RID-1")

    assert captured["datasets"] == [KnowledgeBase._resolve_dataset_alias("kb_profile_99")]


@pytest.mark.asyncio
async def test_md5_files_are_promoted_to_sha_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alias = "kb_profile_5"
    storage_root = tmp_path / "cognee"
    storage_root.mkdir()
    original_text = " Legacy text with spacing "
    normalized = KnowledgeBase._normalize_text(original_text)
    digest_md5 = md5(normalized.encode("utf-8")).hexdigest()
    md5_path = storage_root / f"text_{digest_md5}.txt"
    md5_path.write_text(original_text, encoding="utf-8")

    monkeypatch.setattr(
        KnowledgeBase,
        "_storage_root",
        classmethod(lambda cls: storage_root),
    )

    entries = [DatasetRow(text="", metadata={"digest_md5": digest_md5, "dataset": alias})]
    await KnowledgeBase._heal_dataset_storage(alias, user=None, entries=entries, reason="md5_promotion")

    digest_sha = sha256(normalized.encode("utf-8")).hexdigest()
    sha_path = storage_root / f"text_{digest_sha}.txt"
    assert sha_path.exists()
    assert not md5_path.exists()

    hashes = await knowledge_base_module.HashStore.list(alias)
    assert digest_sha in hashes


@pytest.mark.asyncio
async def test_project_dataset_heals_missing_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    alias = "kb_profile_123"
    text = "Package document\nLine"
    normalized = KnowledgeBase._normalize_text(text)
    digest_md5 = md5(normalized.encode("utf-8")).hexdigest()
    storage_file = tmp_path / f"text_{digest_md5}.txt"
    recorded_metadata: list[tuple[str, str, Mapping[str, Any] | None]] = []
    KnowledgeBase._PROJECTED_DATASETS.clear()
    KnowledgeBase._DATASET_IDS.clear()
    KnowledgeBase._DATASET_ALIASES.clear()

    async def fake_get_dataset_id(cls, dataset: str, user: Any | None) -> str:
        return "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    async def fake_list_entries(cls, dataset: str, user: Any | None) -> list[DatasetRow]:
        return [DatasetRow(text=text, metadata={"dataset": alias})]

    async def fake_hash_add(cls, dataset: str, digest: str, metadata: Mapping[str, Any] | None = None) -> None:
        recorded_metadata.append((dataset, digest, metadata))

    async def fake_get_md5(cls, dataset: str, digest_sha: str) -> str | None:
        return None

    async def fake_wait(
        cls,
        dataset: str,
        user: Any | None,
        *,
        timeout_s: float,
    ) -> ProjectionStatus:
        return ProjectionStatus.READY

    call_state = {"count": 0}

    async def fake_cognify(*_args: Any, **_kwargs: Any) -> None:
        call_state["count"] += 1
        if call_state["count"] == 1:
            raise FileNotFoundError(str(storage_file))

    monkeypatch.setattr(KnowledgeBase, "_storage_root", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(
        knowledge_base_module.CogneeConfig,
        "describe_storage",
        classmethod(
            lambda cls: {
                "root": str(tmp_path),
                "root_exists": True,
                "root_writable": True,
                "entries_count": 0,
                "entries_sample": [],
                "package_path": str(tmp_path / ".package"),
                "package_exists": False,
                "package_is_symlink": False,
                "package_target": None,
            }
        ),
    )
    monkeypatch.setattr(KnowledgeBase, "_list_dataset_entries", classmethod(fake_list_entries))
    monkeypatch.setattr(KnowledgeBase, "_get_dataset_id", classmethod(fake_get_dataset_id))
    monkeypatch.setattr(KnowledgeBase, "_wait_for_projection", classmethod(fake_wait))
    monkeypatch.setattr(KnowledgeBase, "_ensure_dataset_exists", classmethod(lambda cls, dataset, user: None))
    monkeypatch.setattr(knowledge_base_module.HashStore, "add", classmethod(fake_hash_add))
    monkeypatch.setattr(knowledge_base_module.HashStore, "get_md5_for_sha", classmethod(fake_get_md5))
    monkeypatch.setattr(knowledge_base_module.cognee, "cognify", fake_cognify)

    user = SimpleNamespace(id="user-1")
    await KnowledgeBase._project_dataset(alias, user)

    assert call_state["count"] == 2
    assert storage_file.exists()
    assert storage_file.read_text(encoding="utf-8") == normalized
    assert recorded_metadata


@pytest.mark.asyncio
async def test_ensure_global_projected_heals_before_retry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dataset = KnowledgeBase.GLOBAL_DATASET
    alias = KnowledgeBase._resolve_dataset_alias(dataset)
    text = "Global fallback doc"
    normalized = KnowledgeBase._normalize_text(text)
    digest_md5 = md5(normalized.encode("utf-8")).hexdigest()
    storage_file = tmp_path / f"text_{digest_md5}.txt"
    KnowledgeBase._PROJECTED_DATASETS.clear()
    KnowledgeBase._DATASET_IDS.clear()
    KnowledgeBase._DATASET_ALIASES.clear()
    tracker: dict[str, Any] = {"heal_calls": []}

    async def fake_get_user(cls) -> Any | None:
        return SimpleNamespace(id="coach")

    async def fake_get_dataset_id(cls, dataset_name: str, user: Any | None) -> str:
        return "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    async def fake_list_entries(cls, dataset_name: str, user: Any | None) -> list[DatasetRow]:
        return [DatasetRow(text=text, metadata={"dataset": alias})]

    async def fake_hash_add(cls, dataset_name: str, digest: str, metadata: Mapping[str, Any] | None = None) -> None:
        tracker["heal_calls"].append(("add", dataset_name, digest))

    async def fake_get_md5(cls, dataset_name: str, digest_sha: str) -> str | None:
        return None

    wait_state = {"count": 0}

    async def fake_wait(
        cls,
        dataset_name: str,
        user: Any | None,
        *,
        timeout_s: float,
    ) -> ProjectionStatus:
        wait_state["count"] += 1
        return ProjectionStatus.READY if wait_state["count"] >= 2 else ProjectionStatus.TIMEOUT

    original_heal = KnowledgeBase._heal_dataset_storage.__func__

    async def tracking_heal(
        cls,
        dataset_name: str,
        user: Any | None,
        *,
        entries: Sequence[DatasetRow] | None = None,
        reason: str,
    ) -> tuple[int, int]:
        result = await original_heal(cls, dataset_name, user, entries=entries, reason=reason)
        tracker["heal_calls"].append(("heal", dataset_name, reason, result))
        return result

    monkeypatch.setattr(KnowledgeBase, "_storage_root", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(KnowledgeBase, "_get_cognee_user", classmethod(fake_get_user))
    monkeypatch.setattr(KnowledgeBase, "_get_dataset_id", classmethod(fake_get_dataset_id))
    monkeypatch.setattr(KnowledgeBase, "_list_dataset_entries", classmethod(fake_list_entries))
    monkeypatch.setattr(KnowledgeBase, "_wait_for_projection", classmethod(fake_wait))
    monkeypatch.setattr(KnowledgeBase, "_heal_dataset_storage", classmethod(tracking_heal))
    monkeypatch.setattr(KnowledgeBase, "_ensure_dataset_exists", classmethod(lambda cls, dataset_name, user: None))
    monkeypatch.setattr(
        knowledge_base_module.CogneeConfig,
        "describe_storage",
        classmethod(
            lambda cls: {
                "root": str(tmp_path),
                "root_exists": True,
                "root_writable": True,
                "entries_count": 0,
                "entries_sample": [],
                "package_path": str(tmp_path / ".package"),
                "package_exists": False,
                "package_is_symlink": False,
                "package_target": None,
            }
        ),
    )
    monkeypatch.setattr(knowledge_base_module.HashStore, "add", classmethod(fake_hash_add))
    monkeypatch.setattr(knowledge_base_module.HashStore, "get_md5_for_sha", classmethod(fake_get_md5))

    status = await KnowledgeBase.ensure_global_projected(timeout=1.0)

    assert status == ProjectionStatus.READY
    assert wait_state["count"] >= 2
    assert storage_file.exists()
    assert storage_file.read_text(encoding="utf-8") == normalized
    assert any(item[0] == "heal" for item in tracker["heal_calls"])
    assert KnowledgeBase._alias_for_dataset(alias) in KnowledgeBase._PROJECTED_DATASETS

    KnowledgeBase._PROJECTED_DATASETS.clear()


def test_prepare_dataset_row_reads_storage_when_text_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    raw_text = "  Knowledge entry  "
    normalized = KnowledgeBase._normalize_text(raw_text)
    digest_md5 = md5(normalized.encode("utf-8")).hexdigest()
    (tmp_path / f"text_{digest_md5}.txt").write_text(raw_text, encoding="utf-8")

    row = SimpleNamespace(
        text="",
        metadata={"digest_md5": digest_md5, "kind": "document"},
        raw_data_location=f"file:///ignored/text_{digest_md5}.txt",
    )

    monkeypatch.setattr(KnowledgeBase, "_storage_root", classmethod(lambda cls: tmp_path))

    prepared = KnowledgeBase._prepare_dataset_row(row, KnowledgeBase.GLOBAL_DATASET)

    assert prepared.text == normalized
    assert prepared.metadata is not None
    assert prepared.metadata.get("digest_md5") == digest_md5
    assert prepared.metadata.get("digest_sha") == sha256(normalized.encode("utf-8")).hexdigest()
    assert prepared.metadata.get("dataset") == KnowledgeBase.GLOBAL_DATASET


@pytest.mark.asyncio
async def test_projection_ready_with_messages_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    message_text = "client: hello"
    normalized = KnowledgeBase._normalize_text(message_text)
    digest_md5 = md5(normalized.encode("utf-8")).hexdigest()
    (tmp_path / f"text_{digest_md5}.txt").write_text(message_text, encoding="utf-8")

    async def fake_fetch_rows(
        cls,
        list_data: Callable[..., Awaitable[Iterable[Any]]],
        dataset: str,
        user: Any | None,
    ) -> list[Any]:
        return [
            SimpleNamespace(
                text="",
                metadata={"digest_md5": digest_md5, "kind": "message", "role": "client"},
                raw_data_location=f"file:///ignored/text_{digest_md5}.txt",
            )
        ]

    async def fake_search(*_args: Any, **_kwargs: Any) -> list[Any]:
        return []

    alias = KnowledgeBase._dataset_name(123)
    KnowledgeBase._PROJECTED_DATASETS.discard(alias)
    KnowledgeBase._PROJECTION_STATE.pop(alias, None)

    monkeypatch.setattr(KnowledgeBase, "_storage_root", classmethod(lambda cls: tmp_path))
    user_ctx = SimpleNamespace(id=UUID(int=0))
    monkeypatch.setattr(KnowledgeBase, "_ensure_dataset_exists", classmethod(lambda cls, dataset, user: None))
    monkeypatch.setattr(KnowledgeBase, "_get_dataset_id", classmethod(lambda cls, dataset, user: "uuid"))
    monkeypatch.setattr(KnowledgeBase, "_to_user_ctx", classmethod(lambda cls, user: user_ctx))
    monkeypatch.setattr(KnowledgeBase, "_fetch_dataset_rows", classmethod(fake_fetch_rows))
    monkeypatch.setattr(
        knowledge_base_module.cognee,
        "datasets",
        SimpleNamespace(list_data=lambda *args, **kwargs: None),
        raising=False,
    )
    monkeypatch.setattr(knowledge_base_module.cognee, "search", fake_search, raising=False)

    ready, reason = await KnowledgeBase._is_projection_ready(alias, user_ctx)

    assert ready is True
    assert reason.startswith("all_rows_empty_content")


@pytest.mark.asyncio
async def test_projection_uses_uuid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dataset_id = "123e4567-e89b-12d3-a456-426614174000"
    captured: dict[str, Any] = {}

    async def fake_list_data(dataset_id_arg: str, user: Any | None = None) -> list[DatasetRow]:
        captured["dataset_id"] = dataset_id_arg
        captured["user"] = user
        return [DatasetRow(text="Doc", metadata={"kind": "document"})]

    async def fake_search(*args: Any, **kwargs: Any) -> list[Any]:
        return []

    normalized = KnowledgeBase._normalize_text("Doc")
    digest_md5 = md5(normalized.encode("utf-8")).hexdigest()
    (tmp_path / f"text_{digest_md5}.txt").write_text(normalized, encoding="utf-8")

    monkeypatch.setattr(KnowledgeBase, "_DATASET_IDS", {KnowledgeBase.GLOBAL_DATASET: dataset_id})
    monkeypatch.setattr(KnowledgeBase, "_DATASET_ALIASES", {dataset_id: KnowledgeBase.GLOBAL_DATASET})
    monkeypatch.setattr(KnowledgeBase, "_list_data_supports_user", None)
    monkeypatch.setattr(KnowledgeBase, "_list_data_requires_user", None)
    monkeypatch.setattr(
        knowledge_base_module,
        "cognee",
        SimpleNamespace(datasets=SimpleNamespace(list_data=fake_list_data), search=fake_search),
    )
    monkeypatch.setattr(KnowledgeBase, "_storage_root", classmethod(lambda cls: tmp_path))

    user_ctx = SimpleNamespace(id="user-1")
    projected, reason = await KnowledgeBase._is_projection_ready(
        KnowledgeBase.GLOBAL_DATASET,
        user_ctx,
    )

    assert projected is True
    assert captured["dataset_id"] == dataset_id
    assert captured["user"].id == user_ctx.id


@pytest.mark.asyncio
async def test_ensure_global_projected_timeout_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    datasets_used: list[list[str]] = []

    async def fake_search_single_query(
        cls,
        query: str,
        datasets: list[str],
        user: Any | None,
        k: int | None,
        profile_id: int,
        *,
        request_id: str | None = None,
    ) -> list[KnowledgeSnippet]:
        datasets_used.append(list(datasets))
        return []

    async def fake_ensure_profile_indexed(cls, profile_id: int, user: Any | None) -> None:
        return None

    async def fake_ensure_dataset_exists(cls, name: str, user: Any | None) -> None:
        return None

    async def fake_get_user(cls) -> Any | None:
        return SimpleNamespace(id="user-2")

    async def fake_ensure_global_projected(cls, *, timeout: float | None = None) -> ProjectionStatus:
        return ProjectionStatus.TIMEOUT

    monkeypatch.setattr(KnowledgeBase, "_PROJECTED_DATASETS", set())
    monkeypatch.setattr(KnowledgeBase, "_ensure_profile_indexed", classmethod(fake_ensure_profile_indexed))
    monkeypatch.setattr(KnowledgeBase, "_ensure_dataset_exists", classmethod(fake_ensure_dataset_exists))
    monkeypatch.setattr(KnowledgeBase, "_search_single_query", classmethod(fake_search_single_query))
    monkeypatch.setattr(KnowledgeBase, "_get_cognee_user", classmethod(fake_get_user))
    monkeypatch.setattr(KnowledgeBase, "ensure_global_projected", classmethod(fake_ensure_global_projected))

    results = await KnowledgeBase.search("pending projection", profile_id=5, k=3, request_id="req-5")

    assert results == []
    assert datasets_used == [[KnowledgeBase._dataset_name(5)]]


@pytest.mark.asyncio
async def test_global_projection_ready_with_document(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset_id = "123e4567-e89b-12d3-a456-426614174111"

    async def fake_list_data(dataset_id_arg: str, user: Any | None = None) -> list[DatasetRow]:
        assert dataset_id_arg == dataset_id
        return [DatasetRow(text="Intro", metadata={"kind": "document"})]

    async def fake_search(*args: Any, **kwargs: Any) -> list[Any]:
        return []

    async def fake_get_user(cls) -> Any | None:
        return SimpleNamespace(id="user-3")

    async def fake_ensure_dataset_exists(cls, name: str, user: Any | None) -> None:
        cls._register_dataset_identifier(name, dataset_id)

    monkeypatch.setattr(KnowledgeBase, "_DATASET_IDS", {KnowledgeBase.GLOBAL_DATASET: dataset_id})
    monkeypatch.setattr(KnowledgeBase, "_DATASET_ALIASES", {dataset_id: KnowledgeBase.GLOBAL_DATASET})
    monkeypatch.setattr(KnowledgeBase, "_list_data_supports_user", None)
    monkeypatch.setattr(KnowledgeBase, "_list_data_requires_user", None)
    monkeypatch.setattr(KnowledgeBase, "_PROJECTED_DATASETS", set())
    monkeypatch.setattr(KnowledgeBase, "_get_cognee_user", classmethod(fake_get_user))
    monkeypatch.setattr(KnowledgeBase, "_ensure_dataset_exists", classmethod(fake_ensure_dataset_exists))
    monkeypatch.setattr(
        knowledge_base_module,
        "cognee",
        SimpleNamespace(datasets=SimpleNamespace(list_data=fake_list_data), search=fake_search),
    )

    status = await KnowledgeBase.ensure_global_projected(timeout=1.0)

    assert status == ProjectionStatus.READY


def test_fallback_entries_skip_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_list_dataset_entries(self, dataset: str, user: Any | None) -> list[DatasetRow]:
        return [
            DatasetRow(text=" document ", metadata={"kind": "document", "dataset": dataset}),
            DatasetRow(text="client: hi", metadata={"kind": "message", "role": "client", "dataset": dataset}),
        ]

    kb = KnowledgeBase()
    monkeypatch.setattr(kb.dataset_service.__class__, "list_dataset_entries", fake_list_dataset_entries, raising=False)
    monkeypatch.setattr(
        knowledge_base_module.HashStore,
        "add",
        classmethod(_fake_hash_add),
    )

    async def runner() -> list[tuple[str, str]]:
        return await kb.search_service._fallback_dataset_entries(["kb_global"], user_ctx=None, top_k=5)

    results = asyncio.run(runner())
    assert results == [("document", "kb_global")]


def test_build_snippets_skip_unindexed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_collect_metadata(
        cls, digest: str, datasets: Sequence[str]
    ) -> tuple[str | None, dict[str, Any] | None]:  # type: ignore[override]
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
    expected_ids = ["KB-1", "KB-3"]
    assert ids == expected_ids
    assert entries == ["doc", "other"]


def test_build_snippets_accepts_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_collect(cls, digest: str, datasets: Sequence[str]) -> tuple[str | None, dict[str, Any] | None]:
        raise AssertionError("_collect_metadata should not be called when metadata is provided")

    monkeypatch.setattr(KnowledgeBase, "_collect_metadata", classmethod(fail_collect))
    monkeypatch.setattr(
        knowledge_base_module.HashStore,
        "add",
        classmethod(_fake_hash_add),
    )

    sample = {"text": "Document", "metadata": {"kind": "document", "dataset": "kb_global"}}
    snippets = asyncio.run(KnowledgeBase._build_snippets([sample], ["kb_global"], user=None))
    assert [item.text for item in snippets] == ["Document"]
    assert snippets[0].dataset == "kb_global"
    assert snippets[0].kind == "document"


def test_build_snippets_accepts_object(monkeypatch: pytest.MonkeyPatch) -> None:
    @dataclass
    class Result:
        text: str
        metadata: dict[str, Any]
        dataset_name: str

    async def fail_collect(cls, digest: str, datasets: Sequence[str]) -> tuple[str | None, dict[str, Any] | None]:
        raise AssertionError("_collect_metadata should not be called for object results")

    monkeypatch.setattr(KnowledgeBase, "_collect_metadata", classmethod(fail_collect))
    monkeypatch.setattr(
        knowledge_base_module.HashStore,
        "add",
        classmethod(_fake_hash_add),
    )

    item = Result(text="Note entry", metadata={"kind": "note"}, dataset_name="kb_profile_5")
    snippets = asyncio.run(KnowledgeBase._build_snippets([item], ["kb_profile_5"], user=None))
    assert [snippet.text for snippet in snippets] == ["Note entry"]
    assert snippets[0].dataset == "kb_profile_5"
    assert snippets[0].kind == "note"
