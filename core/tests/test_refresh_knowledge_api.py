import base64
import pytest
from httpx import AsyncClient

from ai_coach.application import app
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from config.app_settings import settings


@pytest.mark.asyncio
async def test_refresh_knowledge(monkeypatch):
    monkeypatch.setattr(settings, "AI_COACH_REFRESH_USER", "user")
    monkeypatch.setattr(settings, "AI_COACH_REFRESH_PASSWORD", "pass")
    called: bool = False

    async def fake_refresh(cls):
        nonlocal called
        called = True

    monkeypatch.setattr(KnowledgeBase, "refresh", classmethod(fake_refresh))
    token = base64.b64encode(b"user:pass").decode()
    headers = {"Authorization": f"Basic {token}"}

    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.post("/knowledge/refresh/", headers=headers)

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert called


@pytest.mark.asyncio
async def test_refresh_knowledge_unauthorized(monkeypatch):
    monkeypatch.setattr(settings, "AI_COACH_REFRESH_USER", "user")
    monkeypatch.setattr(settings, "AI_COACH_REFRESH_PASSWORD", "pass")
    token = base64.b64encode(b"user:wrong").decode()
    headers = {"Authorization": f"Basic {token}"}

    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.post("/knowledge/refresh/", headers=headers)

    assert resp.status_code == 401
