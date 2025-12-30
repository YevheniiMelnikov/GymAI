import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest

from apps.metrics import views
from config.app_settings import settings
from core.metrics.constants import METRICS_EVENT_NEW_USER, METRICS_SOURCE_PROFILE


def _sign(secret: str, *, ts: int, body: bytes) -> str:
    message = str(ts).encode() + b"." + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def test_record_metrics_event_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "INTERNAL_KEY_ID", "kid")
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", "secret")
    monkeypatch.setattr("apps.metrics.views.time.time", lambda: 1000)
    captured: dict[str, str] = {}

    def fake_record(event_type: str, source: str, source_id: str) -> bool:
        captured["event_type"] = event_type
        captured["source"] = source
        captured["source_id"] = source_id
        return True

    monkeypatch.setattr("apps.metrics.views.record_event", fake_record)

    payload = {
        "event_type": METRICS_EVENT_NEW_USER,
        "source": METRICS_SOURCE_PROFILE,
        "source_id": "1",
    }
    body = json.dumps(payload).encode()
    signature = _sign("secret", ts=1000, body=body)
    request = SimpleNamespace(
        method="POST",
        body=body,
        headers={"X-Key-Id": "kid", "X-TS": "1000", "X-Sig": signature},
    )

    response = views.record_metrics_event(request)  # type: ignore[arg-type]

    assert response.status_code == 200
    assert json.loads(response.content) == {"status": "ok", "created": True}
    assert captured == payload


def test_record_metrics_event_bad_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "INTERNAL_KEY_ID", "kid")
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", "secret")
    monkeypatch.setattr("apps.metrics.views.time.time", lambda: 1000)

    payload = {
        "event_type": METRICS_EVENT_NEW_USER,
        "source": METRICS_SOURCE_PROFILE,
        "source_id": "1",
    }
    body = json.dumps(payload).encode()
    request = SimpleNamespace(
        method="POST",
        body=body,
        headers={"X-Key-Id": "kid", "X-TS": "1000", "X-Sig": "bad"},
    )

    response = views.record_metrics_event(request)  # type: ignore[arg-type]

    assert response.status_code == 403
