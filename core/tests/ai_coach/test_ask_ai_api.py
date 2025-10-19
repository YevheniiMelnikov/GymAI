import asyncio
import pytest
from httpx import AsyncClient

from ai_coach.application import app
from ai_coach.agent import QAResponse, CoachAgent
from ai_coach.exceptions import AgentExecutionAborted


def test_ask_ai_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def fake_answer(prompt: str, deps: object) -> QAResponse:
            return QAResponse(answer="hi")

        monkeypatch.setattr(CoachAgent, "answer_question", staticmethod(fake_answer))
        async with AsyncClient(app=app, base_url="http://test") as ac:
            resp = await ac.post(
                "/ask/",
                json={"client_id": 1, "prompt": "hello", "mode": "ask_ai"},
                headers={"X-Agent": "pydanticai"},
            )
        assert resp.status_code == 200
        assert resp.json() == {"answer": "hi"}

    asyncio.run(runner())


def test_ask_ai_tool_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def fake_answer(prompt: str, deps: object) -> QAResponse:
            raise RuntimeError("saving not allowed in this mode")

        monkeypatch.setattr(CoachAgent, "answer_question", staticmethod(fake_answer))
        async with AsyncClient(app=app, base_url="http://test") as ac:
            resp = await ac.post(
                "/ask/",
                json={"client_id": 1, "prompt": "hello", "mode": "ask_ai"},
                headers={"X-Agent": "pydanticai"},
            )
        assert resp.status_code == 503

    asyncio.run(runner())


def test_ask_ai_knowledge_base_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def fake_answer(prompt: str, deps: object) -> QAResponse:
            raise AgentExecutionAborted("no kb", reason="knowledge_base_empty")

        monkeypatch.setattr(CoachAgent, "answer_question", staticmethod(fake_answer))
        async with AsyncClient(app=app, base_url="http://test") as ac:
            resp = await ac.post(
                "/ask/",
                json={"client_id": 1, "prompt": "hello", "mode": "ask_ai"},
                headers={"X-Agent": "pydanticai"},
            )
        assert resp.status_code == 408
        payload = resp.json()
        assert payload["reason"] == "knowledge_base_empty"

    asyncio.run(runner())
