import asyncio
import base64
import sys
import types
import pytest
from httpx import AsyncClient

import conftest
from ai_coach.application import app
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from config.app_settings import settings


def _reset_settings(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    settings_mod = sys.modules.get("config.app_settings")
    if settings_mod is None:
        settings_mod = types.ModuleType("config.app_settings")
        sys.modules["config.app_settings"] = settings_mod

    base = types.SimpleNamespace(**conftest.settings_stub.__dict__)
    monkeypatch.setattr(settings_mod, "settings", base, raising=False)
    monkeypatch.setattr(sys.modules[__name__], "settings", base, raising=False)
    return base


def test_refresh_knowledge(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        cfg = _reset_settings(monkeypatch)
        cfg.AI_COACH_REFRESH_USER = "user"
        cfg.AI_COACH_REFRESH_PASSWORD = "pass"
        called: bool = False

        async def fake_refresh(cls) -> None:
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

    asyncio.run(runner())


def test_refresh_knowledge_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        cfg = _reset_settings(monkeypatch)
        cfg.AI_COACH_REFRESH_USER = "user"
        cfg.AI_COACH_REFRESH_PASSWORD = "pass"
        token = base64.b64encode(b"user:wrong").decode()
        headers = {"Authorization": f"Basic {token}"}

        async with AsyncClient(app=app, base_url="http://test") as ac:
            resp = await ac.post("/knowledge/refresh/", headers=headers)

        assert resp.status_code == 401

    asyncio.run(runner())
