import asyncio
import pytest
from types import SimpleNamespace

from ai_coach.api import refresh_knowledge
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from config.app_settings import settings


def test_refresh_knowledge(monkeypatch):
    monkeypatch.setattr(settings, "AI_COACH_REFRESH_USER", "user", raising=False)
    monkeypatch.setattr(settings, "AI_COACH_REFRESH_PASSWORD", "pass", raising=False)
    called: bool = False

    async def fake_refresh(cls):
        nonlocal called
        called = True

    monkeypatch.setattr(KnowledgeBase, "refresh", classmethod(fake_refresh))
    cred = SimpleNamespace(username="user", password="pass")
    result = asyncio.run(refresh_knowledge(cred))
    assert result == {"status": "ok"} and called


def test_refresh_knowledge_unauthorized(monkeypatch):
    monkeypatch.setattr(settings, "AI_COACH_REFRESH_USER", "user", raising=False)
    monkeypatch.setattr(settings, "AI_COACH_REFRESH_PASSWORD", "pass", raising=False)
    cred = SimpleNamespace(username="user", password="wrong")
    with pytest.raises(Exception):
        asyncio.run(refresh_knowledge(cred))
