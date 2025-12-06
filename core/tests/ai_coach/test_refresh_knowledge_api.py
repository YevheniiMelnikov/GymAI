import asyncio
import sys
import types
import hmac
import time
import pytest
from httpx import AsyncClient, ASGITransport

from core.tests import conftest
from ai_coach.application import app
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase


def _reset_settings(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    settings_mod = sys.modules.get("config.app_settings")
    if settings_mod is None:
        settings_mod = types.ModuleType("config.app_settings")
        sys.modules["config.app_settings"] = settings_mod

    base = types.SimpleNamespace(**conftest.settings_stub.__dict__)
    monkeypatch.setattr(settings_mod, "settings", base, raising=False)
    monkeypatch.setattr(sys.modules[__name__], "settings", base, raising=False)
    import ai_coach.api as coach_api
    import ai_coach.api_security as api_security

    monkeypatch.setattr(api_security, "app_settings", settings_mod, raising=False)
    monkeypatch.setattr(api_security, "settings", base, raising=False)
    monkeypatch.setattr(coach_api, "settings", base, raising=False)
    coach_api.app.dependency_overrides.pop(coach_api._require_hmac, None)
    return base


def test_refresh_knowledge(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        cfg = _reset_settings(monkeypatch)
        cfg.ENVIRONMENT = "production"
        cfg.AI_COACH_INTERNAL_KEY_ID = "key"
        cfg.AI_COACH_INTERNAL_API_KEY = "secret"
        cfg.INTERNAL_KEY_ID = ""
        cfg.INTERNAL_API_KEY = ""
        called: bool = False

        async def fake_refresh(cls) -> None:
            nonlocal called
            called = True

        monkeypatch.setattr(KnowledgeBase, "refresh", classmethod(fake_refresh))
        import ai_coach.api as coach_api

        coach_api.app.dependency_overrides.pop(coach_api._require_hmac, None)
        ts = int(time.time())
        body = b""
        message = f"{ts}".encode() + b"." + body
        sig = hmac.new(cfg.AI_COACH_INTERNAL_API_KEY.encode(), message, "sha256").hexdigest()
        headers = {"X-Key-Id": cfg.AI_COACH_INTERNAL_KEY_ID, "X-TS": str(ts), "X-Sig": sig}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/knowledge/refresh/", headers=headers, content=body)

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        assert called

    asyncio.run(runner())


def test_refresh_knowledge_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        cfg = _reset_settings(monkeypatch)
        cfg.ENVIRONMENT = "production"
        cfg.AI_COACH_INTERNAL_KEY_ID = ""
        cfg.AI_COACH_INTERNAL_API_KEY = ""
        cfg.INTERNAL_KEY_ID = ""
        cfg.INTERNAL_API_KEY = ""
        import ai_coach.api as coach_api

        coach_api.app.dependency_overrides.pop(coach_api._require_hmac, None)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/knowledge/refresh/")

        assert resp.status_code == 503

    asyncio.run(runner())
