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

        resp = client.post("/coach/chat/", json={"profile_id": 1, "prompt": "hi", "mode": "ask_ai"})
        assert resp.status_code == 403

        body = b'{"profile_id":1,"prompt":"hi","mode":"ask_ai"}'
        headers = build_internal_hmac_auth_headers(
            key_id=settings.AI_COACH_INTERNAL_KEY_ID,
            secret_key=settings.AI_COACH_INTERNAL_API_KEY,
            body=body,
        )
        headers["Content-Type"] = "application/json"
        headers["X-TS"] = str(int(time.time()))

        resp_ok = client.post("/coach/chat/", content=body, headers=headers)
        assert resp_ok.status_code in {200, 408, 422, 503}  # downstream agent may abort but HMAC passes
    finally:
        settings.ENVIRONMENT = prev_env
        settings.AI_COACH_INTERNAL_KEY_ID = prev_key_id
        settings.AI_COACH_INTERNAL_API_KEY = prev_secret
