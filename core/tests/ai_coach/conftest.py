import pytest

import ai_coach.api as coach_api
from ai_coach.application import app
from config.app_settings import settings


@pytest.fixture(autouse=True)
def _override_hmac(monkeypatch: pytest.MonkeyPatch):
    """Disable HMAC checks and set deterministic keys for tests."""

    monkeypatch.setattr(settings, "AI_COACH_INTERNAL_KEY_ID", "test-key")
    monkeypatch.setattr(settings, "AI_COACH_INTERNAL_API_KEY", "test-secret")
    monkeypatch.setattr(settings, "INTERNAL_KEY_ID", "test-key")
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", "test-secret")

    app.dependency_overrides[coach_api._require_hmac] = lambda: None
    yield
    app.dependency_overrides.pop(coach_api._require_hmac, None)
