import asyncio
import pytest  # pyrefly: ignore[import-error]

from pydantic_ai import ModelRetry  # pyrefly: ignore[import-error]

from ai_coach.agent import AgentDeps
from ai_coach.agent.tools import tool_search_knowledge
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase


class _Ctx:
    def __init__(self):
        self.deps = AgentDeps(client_id=1)


def test_tool_search_knowledge_k(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        called: dict[str, int] = {}

        async def fake_search(query: str, client_id: int, k: int) -> list[str]:
            called["k"] = k
            called["client_id"] = client_id
            return []

        monkeypatch.setattr(KnowledgeBase, "search", fake_search)
        ctx = _Ctx()
        result = await tool_search_knowledge(ctx, "hi", k=5)
        assert result == []
        assert called["k"] == 5
        assert called["client_id"] == 1
        assert ctx.deps.last_knowledge_query == "hi"
        assert ctx.deps.last_knowledge_empty is True

    asyncio.run(runner())


def test_tool_search_knowledge_duplicate_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def fake_search(query: str, client_id: int, k: int) -> list[str]:
            return []

        monkeypatch.setattr(KnowledgeBase, "search", fake_search)
        ctx = _Ctx()
        await tool_search_knowledge(ctx, "  hello  ")
        with pytest.raises(ModelRetry):
            await tool_search_knowledge(ctx, "hello")

    asyncio.run(runner())
