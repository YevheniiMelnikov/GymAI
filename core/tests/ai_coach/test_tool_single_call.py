from types import SimpleNamespace

import pytest  # pyrefly: ignore[import-error]

from pydantic_ai import ModelRetry  # pyrefly: ignore[import-error]

from ai_coach.agent import AgentDeps
from ai_coach.types import CoachMode
from ai_coach.agent.tools import tool_search_knowledge


@pytest.mark.asyncio
async def test_tool_search_knowledge_skips_repeat(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class DummyKnowledgeBase:
        @staticmethod
        async def search(query: str, client_id: int, k: int) -> list[str]:
            calls.append(query)
            return [f"result:{query}"]

    monkeypatch.setattr("ai_coach.agent.tools.KnowledgeBase", DummyKnowledgeBase)
    deps = AgentDeps(client_id=1)
    deps.mode = CoachMode.program
    ctx = SimpleNamespace(deps=deps)
    first = await tool_search_knowledge(ctx, "Goal", k=2)
    assert first == ["result:Goal"]
    with pytest.raises(ModelRetry) as exc:
        await tool_search_knowledge(ctx, "Different", k=3)
    assert "already executed" in str(exc.value)
    assert calls == ["Goal"]
