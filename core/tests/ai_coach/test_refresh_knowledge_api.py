import base64
import sys
import types
from typing import Any

from starlette.testclient import TestClient

import ai_coach.application as application_module
from ai_coach.application import app
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from core.tests import conftest


def _reset_settings(monkeypatch: Any) -> types.SimpleNamespace:
    settings_mod = sys.modules.get("config.app_settings")
    if settings_mod is None:
        settings_mod = types.ModuleType("config.app_settings")
        sys.modules["config.app_settings"] = settings_mod

    base = types.SimpleNamespace(**conftest.settings_stub.__dict__)
    monkeypatch.setattr(settings_mod, "settings", base, raising=False)
    monkeypatch.setattr(sys.modules[__name__], "settings", base, raising=False)

    import ai_coach.api as coach_api_module
    import ai_coach.api_security as api_security_module

    monkeypatch.setattr(api_security_module, "app_settings", settings_mod, raising=False)
    monkeypatch.setattr(api_security_module, "settings", base, raising=False)
    monkeypatch.setattr(coach_api_module, "settings", base, raising=False)
    coach_api_module.app.dependency_overrides.pop(coach_api_module._require_hmac, None)
    return base


def _patch_lifespan_helpers(monkeypatch: Any) -> None:
    async def _noop_init(_kb: KnowledgeBase, _loader: Any | None = None) -> None:
        return None

    class _DummyLoader:
        def __init__(self, kb: KnowledgeBase) -> None:
            self.kb = kb

    monkeypatch.setattr(application_module, "init_knowledge_base", _noop_init, raising=False)
    monkeypatch.setattr(application_module, "GDriveDocumentLoader", _DummyLoader, raising=False)


def _basic_auth_header(user: str, password: str) -> dict[str, str]:
    credentials = f"{user}:{password}"
    token = base64.b64encode(credentials.encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_refresh_knowledge(monkeypatch: Any) -> None:
    cfg = _reset_settings(monkeypatch)
    cfg.ENVIRONMENT = "production"
    cfg.AI_COACH_REFRESH_USER = "admin"
    cfg.AI_COACH_REFRESH_PASSWORD = "password"

    _patch_lifespan_helpers(monkeypatch)

    called = False

    async def fake_refresh(self: KnowledgeBase, force: bool = False) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(KnowledgeBase, "refresh", fake_refresh, raising=False)

    headers = _basic_auth_header(cfg.AI_COACH_REFRESH_USER, cfg.AI_COACH_REFRESH_PASSWORD)
    print("TEST: entering TestClient context")
    with TestClient(app) as client:
        print("TEST: sending request")
        response = client.post("/knowledge/refresh/?force=False", headers=headers)
        print("TEST: response status", response.status_code)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert called


def test_refresh_knowledge_unauthorized(monkeypatch: Any) -> None:
    cfg = _reset_settings(monkeypatch)
    cfg.ENVIRONMENT = "production"
    cfg.AI_COACH_REFRESH_USER = "admin"
    cfg.AI_COACH_REFRESH_PASSWORD = "password"

    _patch_lifespan_helpers(monkeypatch)

    headers = _basic_auth_header("wrong_user", "wrong_password")
    with TestClient(app) as client:
        response = client.post("/knowledge/refresh/?force=False", headers=headers)

    assert response.status_code == 401
