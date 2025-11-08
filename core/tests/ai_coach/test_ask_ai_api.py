import asyncio
import base64

import pytest
from httpx import AsyncClient

from ai_coach.application import app
from ai_coach.agent import QAResponse, CoachAgent
from ai_coach.exceptions import AgentExecutionAborted


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {token}"}


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


def test_ask_ai_model_empty_response(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def fake_answer(prompt: str, deps: object) -> QAResponse:
            raise AgentExecutionAborted("empty", reason="model_empty_response")

        monkeypatch.setattr(CoachAgent, "answer_question", staticmethod(fake_answer))
        async with AsyncClient(app=app, base_url="http://test") as ac:
            resp = await ac.post(
                "/ask/",
                json={"client_id": 1, "prompt": "hello", "mode": "ask_ai"},
                headers={"X-Agent": "pydanticai"},
            )
        assert resp.status_code == 408
        payload = resp.json()
        assert payload["reason"] == "model_empty_response"

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


def test_llm_probe_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def fake_probe(cls: type[CoachAgent]) -> dict[str, object]:  # type: ignore[override]
            return {
                "model": "test",
                "content_length": 2,
                "has_tool_calls": False,
                "finish_reason": "stop",
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
                "latency_ms": 5.0,
            }

        monkeypatch.setattr(CoachAgent, "llm_probe", classmethod(fake_probe))
        headers = _basic_auth_header("admin", "password")
        async with AsyncClient(app=app, base_url="http://test") as ac:
            resp = await ac.get("/internal/debug/llm_probe", headers=headers)
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["model"] == "test"

    asyncio.run(runner())
