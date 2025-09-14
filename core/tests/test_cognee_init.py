import asyncio
import pytest
from types import SimpleNamespace

from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
import ai_coach.agent.knowledge.knowledge_base as coach
from ai_coach.application import knowledge_ready_event, init_knowledge_base


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
        if knowledge_ready_event is not None:
            knowledge_ready_event.clear()
        with pytest.raises(RuntimeError):
            await init_knowledge_base()

        async def ok(*args, **kwargs):
            KnowledgeBase._user = SimpleNamespace(id="ok")

        monkeypatch.setattr(KnowledgeBase, "initialize", ok)
        await init_knowledge_base()
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

        res = await KnowledgeBase.search("hello", client_id=42)
        assert calls == [["client_42", coach.KnowledgeBase.GLOBAL_DATASET]]
        assert res == []

    asyncio.run(runner())
