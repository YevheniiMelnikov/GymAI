import asyncio
from typing import Any
import pytest  # pyrefly: ignore[import-error]

from ai_coach.agent import AgentDeps
from ai_coach.exceptions import AgentExecutionAborted
from ai_coach.agent import tools as agent_tools
from ai_coach.agent.tools import tool_get_chat_history, tool_search_knowledge
from core.tests.conftest import _KB

KnowledgeBase = agent_tools.KnowledgeBase


def _patch_kb_attr(monkeypatch: pytest.MonkeyPatch, attr: str, value: Any) -> None:
    monkeypatch.setattr(KnowledgeBase, attr, value, raising=False)
    monkeypatch.setattr(_KB, attr, value, raising=False)


class _Ctx:
    def __init__(self, *, deps: AgentDeps | None = None):
        self.deps = deps or AgentDeps(profile_id=1, max_tool_calls=10)


def test_tool_search_knowledge_k(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        called: dict[str, int] = {}

        async def fake_search(cls, query: str, profile_id: int, k: int, **kwargs: Any) -> list[str]:
            called["k"] = k
            called["profile_id"] = profile_id
            return []

        async def fake_fallback_entries(profile_id: int, limit: int = 6) -> list[tuple[str, str]]:
            return []

        _patch_kb_attr(monkeypatch, "search", fake_search)
        _patch_kb_attr(monkeypatch, "fallback_entries", fake_fallback_entries)
        ctx = _Ctx()
        result = await tool_search_knowledge(ctx, "hi", k=5)
        assert result == []
        assert called["k"] == 5
        assert called["profile_id"] == 1
        assert ctx.deps.last_knowledge_query == "hi"
        assert ctx.deps.last_knowledge_empty is True
        assert ctx.deps.knowledge_base_empty is True

    asyncio.run(runner())


def test_tool_search_knowledge_duplicate_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def fake_search(cls, query: str, profile_id: int, k: int, **kwargs: Any) -> list[str]:
            return []

        async def fake_fallback_entries(profile_id: int, limit: int = 6) -> list[tuple[str, str]]:
            return []

        _patch_kb_attr(monkeypatch, "search", fake_search)
        _patch_kb_attr(monkeypatch, "fallback_entries", fake_fallback_entries)
        ctx = _Ctx()
        await tool_search_knowledge(ctx, "  hello  ")
        result = await tool_search_knowledge(ctx, "hello")
        assert result == []

    asyncio.run(runner())


def test_tool_search_knowledge_timeout_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def fake_wait_for(coro: Any, timeout: float) -> list[str]:
            coro.close()
            raise TimeoutError

        async def fake_fallback_entries(profile_id: int, limit: int = 6) -> list[tuple[str, str]]:
            return [("Fallback guidance", "kb_global")]

        monkeypatch.setattr("ai_coach.agent.tools.wait_for", fake_wait_for)
        _patch_kb_attr(monkeypatch, "fallback_entries", fake_fallback_entries)
        ctx = _Ctx()
        result = await tool_search_knowledge(ctx, "timeout case", k=3)
        assert result == ["Fallback guidance"]
        assert ctx.deps.knowledge_base_empty is False
        assert ctx.deps.last_knowledge_empty is False

    asyncio.run(runner())


def test_tool_search_knowledge_uses_fallback_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def fake_search(cls, query: str, profile_id: int, k: int, **kwargs: Any) -> list[str]:
            return []

        async def fake_fallback_entries(profile_id: int, limit: int = 6) -> list[tuple[str, str]]:
            return [(" First entry ", "kb_global"), ("Second entry", "kb_chat_1")]

        _patch_kb_attr(monkeypatch, "search", fake_search)
        _patch_kb_attr(monkeypatch, "fallback_entries", fake_fallback_entries)
        ctx = _Ctx()
        result = await tool_search_knowledge(ctx, "need fallback", k=2)
        assert result == ["First entry", "Second entry"]
        assert ctx.deps.knowledge_base_empty is False
        assert ctx.deps.last_knowledge_empty is False

    asyncio.run(runner())


def test_tool_budget_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def fake_search(cls, query: str, profile_id: int, k: int, **kwargs: Any) -> list[str]:
            return ["result"]

        async def fake_history(profile_id: int, limit: int) -> list[str]:
            return ["msg"]

        _patch_kb_attr(monkeypatch, "search", fake_search)
        _patch_kb_attr(monkeypatch, "get_message_history", fake_history)
        deps = AgentDeps(profile_id=1, max_tool_calls=1)
        ctx = _Ctx(deps=deps)
        await tool_search_knowledge(ctx, "hello")
        with pytest.raises(AgentExecutionAborted):
            await tool_get_chat_history(ctx)

    asyncio.run(runner())


def test_tool_get_chat_history_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        calls: list[int] = []

        async def fake_history(cls_or_self, profile_id: int, limit: int) -> list[str]:
            calls.append(limit)
            return ["msg1", "msg2", "msg3"]

        _patch_kb_attr(monkeypatch, "get_message_history", fake_history)
        ctx = _Ctx()
        first = await tool_get_chat_history(ctx, limit=2)
        second = await tool_get_chat_history(ctx, limit=3)
        assert first == ["msg1", "msg2"]
        assert second == ["msg1", "msg2", "msg3"]
        assert calls == [2]

    asyncio.run(runner())
