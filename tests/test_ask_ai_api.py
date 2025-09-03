import pytest
from httpx import AsyncClient

from ai_coach.application import app
from ai_coach.coach_agent import QAResponse, CoachAgent


@pytest.mark.asyncio
async def test_ask_ai_agent(monkeypatch):
    async def fake_answer(prompt, deps):
        return QAResponse(answer="hi", sources=["c1", "g1"])

    monkeypatch.setattr(CoachAgent, "answer_question", staticmethod(fake_answer))
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.post(
            "/ask/",
            json={"client_id": 1, "prompt": "hello", "mode": "ask_ai"},
            headers={"X-Agent": "pydanticai"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"answer": "hi", "sources": ["c1", "g1"]}


@pytest.mark.asyncio
async def test_ask_ai_tool_error(monkeypatch):
    async def fake_answer(prompt, deps):
        raise RuntimeError("saving not allowed in this mode")

    monkeypatch.setattr(CoachAgent, "answer_question", staticmethod(fake_answer))
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.post(
            "/ask/",
            json={"client_id": 1, "prompt": "hello", "mode": "ask_ai"},
            headers={"X-Agent": "pydanticai"},
        )
    assert resp.status_code == 503
