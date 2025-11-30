import time

from fastapi.testclient import TestClient

import ai_coach.api as coach_api
from ai_coach.application import app
from config.app_settings import settings
from core.internal_http import build_internal_hmac_auth_headers


def test_require_hmac_missing_and_valid():
    app.dependency_overrides.pop(coach_api._require_hmac, None)
    prev_env = settings.ENVIRONMENT
    prev_key_id = settings.AI_COACH_INTERNAL_KEY_ID
    prev_secret = settings.AI_COACH_INTERNAL_API_KEY
    try:
        settings.ENVIRONMENT = "production"
        settings.AI_COACH_INTERNAL_KEY_ID = "test-key"
        settings.AI_COACH_INTERNAL_API_KEY = "secret"

        client = TestClient(app)

        resp = client.get("/internal/debug/ping")
        assert resp.status_code == 403

        headers = build_internal_hmac_auth_headers(
            key_id=settings.AI_COACH_INTERNAL_KEY_ID,
            secret_key=settings.AI_COACH_INTERNAL_API_KEY,
            body=b"",
        )
        headers["X-TS"] = str(int(time.time()))
        resp_ok = client.get("/internal/debug/ping", headers=headers)
        assert resp_ok.status_code == 200
        assert resp_ok.json() == {"ok": True}
    finally:
        settings.ENVIRONMENT = prev_env
        settings.AI_COACH_INTERNAL_KEY_ID = prev_key_id
        settings.AI_COACH_INTERNAL_API_KEY = prev_secret
