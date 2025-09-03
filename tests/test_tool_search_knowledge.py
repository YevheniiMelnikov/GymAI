import pytest

from ai_coach.coach_agent import AgentDeps, tool_search_knowledge
from ai_coach.cognee_coach import CogneeCoach


class _Ctx:
    def __init__(self):
        self.deps = AgentDeps(client_id=1)


@pytest.mark.asyncio
async def test_tool_search_knowledge_k(monkeypatch):
    called = {}

    async def fake_search(query: str, k: int):
        called["k"] = k
        return []

    monkeypatch.setattr(CogneeCoach, "search_knowledge", fake_search)
    ctx = _Ctx()
    result = await tool_search_knowledge(ctx, "hi", k=5)
    assert result == []
    assert called["k"] == 5
