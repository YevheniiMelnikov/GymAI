import hmac
import hashlib
from types import SimpleNamespace

import httpx

from core.internal_http import build_internal_hmac_auth_headers, internal_request_timeout


def test_build_internal_hmac_auth_headers():
    key_id = "test_key_id"
    secret_key = "test_secret_key"
    body = b'{"test": "body"}'

    headers = build_internal_hmac_auth_headers(key_id=key_id, secret_key=secret_key, body=body)

    assert headers["X-Key-Id"] == key_id
    assert "X-TS" in headers
    assert "X-Sig" in headers

    now = headers["X-TS"]
    message = now.encode() + b"." + body
    expected_signature = hmac.new(secret_key.encode(), message, hashlib.sha256).hexdigest()

    assert headers["X-Sig"] == expected_signature


def test_internal_request_timeout_uses_settings() -> None:
    settings = SimpleNamespace(INTERNAL_HTTP_CONNECT_TIMEOUT=2.5, INTERNAL_HTTP_READ_TIMEOUT=7.5)
    timeout = internal_request_timeout(settings)
    if hasattr(httpx, "Timeout"):
        assert isinstance(timeout, httpx.Timeout)
        assert timeout.connect == 2.5
        assert timeout.read == 7.5
        assert timeout.write == 7.5
    else:
        assert timeout == 7.5
