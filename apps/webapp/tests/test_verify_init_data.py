import hashlib
import hmac
import json
from urllib.parse import quote

import pytest

from apps.webapp.utils import verify_init_data
from config.app_settings import settings


def _build_init_data(payload: dict[str, str], token: str) -> str:
    check_string: str = "\n".join(f"{k}={v}" for k, v in sorted(payload.items()))
    secret_key: bytes = hashlib.sha256(token.encode()).digest()
    hash_value: str = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    body: str = "&".join(f"{k}={quote(v, safe='')}" for k, v in payload.items())
    return f"{body}&hash={hash_value}"


def test_verify_init_data_success(monkeypatch: pytest.MonkeyPatch) -> None:
    token: str = "TOKEN"
    monkeypatch.setattr(settings, "BOT_TOKEN", token, raising=False)
    payload: dict[str, str] = {"auth_date": "0", "user": json.dumps({"id": 1})}
    init_data: str = _build_init_data(payload, token)
    data: dict[str, object] = verify_init_data(init_data)
    assert data["auth_date"] == "0"
    assert isinstance(data["user"], dict)
    assert data["user"]["id"] == 1


def test_verify_init_data_with_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    token: str = "TOKEN"
    monkeypatch.setattr(settings, "BOT_TOKEN", token, raising=False)
    payload: dict[str, str] = {"auth_date": "0", "user": json.dumps({"id": 1})}
    init_data: str = _build_init_data(payload, token) + "&signature=dummy"
    data: dict[str, object] = verify_init_data(init_data)
    assert data["auth_date"] == "0"
    assert isinstance(data["user"], dict)
    assert data["user"]["id"] == 1


def test_verify_init_data_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    token: str = "TOKEN"
    monkeypatch.setattr(settings, "BOT_TOKEN", token, raising=False)
    init_data: str = "auth_date=0&hash=deadbeef"
    with pytest.raises(ValueError):
        verify_init_data(init_data)
