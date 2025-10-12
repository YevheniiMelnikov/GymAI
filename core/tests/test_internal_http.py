from types import SimpleNamespace

import httpx

from core.internal_http import build_internal_auth_headers, internal_request_timeout


def test_build_internal_auth_headers_prefers_internal_key() -> None:
    headers = build_internal_auth_headers(internal_api_key="secret", fallback_api_key="public")
    assert headers == {"X-Internal-Api-Key": "secret"}


def test_build_internal_auth_headers_fallback_to_authorization() -> None:
    headers = build_internal_auth_headers(internal_api_key=None, fallback_api_key="public")
    assert headers == {"Authorization": "Api-Key public"}


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
