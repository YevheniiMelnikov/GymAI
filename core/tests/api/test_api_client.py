import httpx
import pytest
import types
import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "api_client", Path(__file__).resolve().parents[2] / "services" / "internal" / "api_client.py"
)
api_client_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(api_client_module)
APIClient = api_client_module.APIClient
APIClientHTTPError = api_client_module.APIClientHTTPError
APIClientTransportError = api_client_module.APIClientTransportError


def make_response(status: int, json_data: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        request=httpx.Request("GET", "http://test"),
        json=json_data,
    )


def _settings() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        API_URL="http://api",
        API_KEY="",
        API_MAX_RETRIES=3,
        API_RETRY_INITIAL_DELAY=0,
        API_RETRY_BACKOFF_FACTOR=1,
        API_RETRY_MAX_DELAY=0,
        API_TIMEOUT=5,
    )


def test_api_request_success(mocker):
    import asyncio

    async def fake_request(*a, **kw):
        return make_response(200, {"ok": True})

    mocker.patch("httpx.AsyncClient.request", fake_request)

    api = APIClient(None, _settings())
    code, data = asyncio.run(api._api_request("get", "http://x"))
    assert code == 200
    assert data == {"ok": True}


def test_api_request_retries(mocker):
    import asyncio

    calls = []

    async def fake_request(*a, **kw):
        calls.append(1)
        if len(calls) < 2:
            response = make_response(502)
            raise httpx.HTTPStatusError("boom", request=response.request, response=response)
        return make_response(200, {"ok": True})

    mocker.patch("httpx.AsyncClient.request", fake_request)

    api = APIClient(None, _settings())
    api.max_retries = 2
    code, _ = asyncio.run(api._api_request("get", "http://x"))
    assert len(calls) == 2
    assert code == 200


def test_api_request_gives_up(mocker):
    import asyncio

    async def fake_request(*a, **kw):
        response = make_response(503)
        raise httpx.HTTPStatusError("boom", request=response.request, response=response)

    mocker.patch("httpx.AsyncClient.request", fake_request)

    api = APIClient(None, _settings())
    api.max_retries = 2
    with pytest.raises(APIClientHTTPError):
        asyncio.run(api._api_request("get", "http://x"))


def test_api_request_transport_error(mocker):
    import asyncio

    async def fake_request(*a, **kw):
        raise httpx.ConnectError("down", request=httpx.Request("GET", "http://x"))

    mocker.patch("httpx.AsyncClient.request", fake_request)

    api = APIClient(None, _settings())
    with pytest.raises(APIClientTransportError):
        asyncio.run(api._api_request("get", "http://x"))


def test_api_request_uses_body_bytes(mocker):
    import asyncio

    called = {}

    async def fake_request(*a, **kw):
        called.update(kw)
        return make_response(200, {"ok": True})

    mocker.patch("httpx.AsyncClient.request", fake_request)

    api = APIClient(None, _settings())
    body = b"raw-body"
    code, data = asyncio.run(api._api_request("post", "http://x", body_bytes=body, data={"ignored": 1}))
    assert code == 200
    assert data == {"ok": True}
    assert called.get("content") == body
    assert "json" not in called
