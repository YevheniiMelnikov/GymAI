import asyncio
from types import SimpleNamespace
from pathlib import Path
from typing import Any

import pytest

from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
import ai_coach.agent.knowledge.knowledge_base as coach
import ai_coach.application as coach_application
from ai_coach.application import init_knowledge_base
from ai_coach.agent.knowledge.cognee_config import _patch_local_file_storage


def test_reinit_on_failure(monkeypatch):
    async def runner():
        called = 0

        async def broken(*args, **kwargs):
            nonlocal called
            called += 1
            if called == 1:
                raise RuntimeError("boom")

        monkeypatch.setattr(KnowledgeBase, "initialize", broken)
        monkeypatch.setattr(KnowledgeBase, "_user", None)

        async def fake_user():
            return SimpleNamespace(id="test")

        monkeypatch.setattr("ai_coach.agent.knowledge.knowledge_base.get_default_user", fake_user)
        if coach_application.knowledge_ready_event is not None:
            coach_application.knowledge_ready_event.clear()
        kb = KnowledgeBase()
        with pytest.raises(RuntimeError):
            await init_knowledge_base(kb)

        async def ok(*args, **kwargs):
            KnowledgeBase._user = SimpleNamespace(id="ok")

        monkeypatch.setattr(KnowledgeBase, "initialize", ok)
        await init_knowledge_base(kb)
        assert KnowledgeBase._user is not None

    asyncio.run(runner())


def test_empty_context_does_not_crash(monkeypatch):
    async def runner():
        KnowledgeBase._user = SimpleNamespace(id="test-u")

        async def noop(*a, **k):
            pass

        monkeypatch.setattr(KnowledgeBase, "_ensure_profile_indexed", noop)

        calls: list[list[str]] = []

        async def fake_search(query, datasets, user=None, top_k=None):
            calls.append(datasets)
            if len(calls) == 1:
                raise coach.DatasetNotFoundError("missing")
            return []

        monkeypatch.setattr(coach.cognee, "search", fake_search)

        res = await KnowledgeBase.search("hello", profile_id=42)
        expected_dataset = KnowledgeBase._dataset_name(42)
        fallback_dataset = coach.KnowledgeBase._resolve_dataset_alias(coach.KnowledgeBase.GLOBAL_DATASET)
        assert calls == [
            [expected_dataset],
            [fallback_dataset],
        ]
        assert res == []

    asyncio.run(runner())


def test_local_file_storage_patch(monkeypatch, tmp_path):
    class DummyStorage:
        _gymbot_storage_patched = False
        storage_path: Path | str = Path("/tmp/old")
        STORAGE_PATH: str = "/tmp/old"

        def open(self, file_path: str, mode: str = "r", **kwargs: Any) -> Any:
            raise FileNotFoundError(file_path)

    monkeypatch.setattr("ai_coach.agent.knowledge.cognee_config._resolve_localfilestorage_class", lambda: DummyStorage)

    sample = tmp_path / "text_abc.txt"
    sample.write_text("hello", encoding="utf-8")

    _patch_local_file_storage(tmp_path)

    storage = DummyStorage()
    with storage.open(sample.name, encoding="utf-8") as handle:
        assert handle.read() == "hello"

    assert DummyStorage._gymbot_storage_patched is True
    assert DummyStorage.storage_path == tmp_path
    assert DummyStorage.STORAGE_PATH == str(tmp_path)
