import asyncio
import pytest
from types import SimpleNamespace

from ai_coach.cognee_coach import CogneeCoach
import ai_coach.cognee_coach as coach
from ai_coach.utils import init_ai_coach, coach_ready_event


def test_reinit_on_failure(monkeypatch):
    async def runner():
        called = 0

        async def broken(*args, **kwargs):
            nonlocal called
            called += 1
            if called == 1:
                raise RuntimeError("boom")

        monkeypatch.setattr(CogneeCoach, "_ensure_config", broken)
        monkeypatch.setattr(CogneeCoach, "_user", None)

        async def fake_user():
            return SimpleNamespace(id="test")

        monkeypatch.setattr("ai_coach.cognee_coach.get_default_user", fake_user)
        if coach_ready_event is not None:
            coach_ready_event.clear()
        with pytest.raises(RuntimeError):
            await init_ai_coach(CogneeCoach)

        async def ok(*args, **kwargs):
            pass

        monkeypatch.setattr(CogneeCoach, "_ensure_config", ok)
        await init_ai_coach(CogneeCoach)
        assert CogneeCoach._user is not None

    asyncio.run(runner())


def test_empty_context_does_not_crash(monkeypatch):
    async def runner():
        CogneeCoach._user = SimpleNamespace(id="test-u")
        monkeypatch.setattr(CogneeCoach, "_ensure_config", lambda: None)

        async def fake_search(query, datasets, user=None, top_k=None):
            if not hasattr(fake_search, "called"):
                fake_search.called = True
                raise coach.DatasetNotFoundError("missing")
            return []

        monkeypatch.setattr(coach.cognee, "search", fake_search)
        async def fake_contains(*a, **k):
            return False

        async def fake_add_hash(*a, **k):
            pass

        monkeypatch.setattr(coach.HashStore, "contains", fake_contains)
        monkeypatch.setattr(coach.HashStore, "add", fake_add_hash)

        res = await CogneeCoach.get_context(chat_id=42, query="hello")
        assert isinstance(res, list)

    asyncio.run(runner())
