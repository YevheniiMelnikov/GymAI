import httpx
import pytest
from unittest.mock import Mock
import importlib.util
from pathlib import Path

from core.exceptions import UserServiceError

spec = importlib.util.spec_from_file_location(
    "api_client", Path(__file__).resolve().parents[1] / "services" / "internal" / "api_client.py"
)
api_client_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(api_client_module)
APIClient = api_client_module.APIClient


class DummyResponse:
    def __init__(self, status_code: int, json_data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.request = httpx.Request("GET", "http://test")
        self.headers = {"content-type": "application/json"}

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict:
        if self._json is None:
            raise httpx.DecodingError("no json")
        return self._json


def test_api_request_success(monkeypatch):
    import asyncio

    async def fake_request(*a, **kw):
        return DummyResponse(200, {"ok": True})

    class _Client:
        async def request(self, *a, **kw):
            return await fake_request(*a, **kw)

    monkeypatch.setattr(APIClient, "_get_client", classmethod(lambda cls, timeout: _Client()))
    code, data = asyncio.run(APIClient._api_request("get", "http://x"))
    assert code == 200
    assert data == {"ok": True}


def test_api_request_retries(monkeypatch):
    import asyncio

    calls = []

    async def fake_request(*a, **kw):
        calls.append(1)
        if len(calls) < 2:
            mock_request = Mock(spec=httpx.Request)
            mock_response = Mock(spec=httpx.Response)
            raise httpx.HTTPStatusError("boom", request=mock_request, response=mock_response)
        return DummyResponse(200, {"ok": True})

    class _Client2:
        async def request(self, *a, **kw):
            return await fake_request(*a, **kw)

    monkeypatch.setattr(APIClient, "_get_client", classmethod(lambda cls, timeout: _Client2()))
    APIClient.max_retries = 2
    code, _ = asyncio.run(APIClient._api_request("get", "http://x"))
    assert len(calls) == 2
    assert code == 200


def test_api_request_gives_up(monkeypatch):
    import asyncio

    async def fake_request(*a, **kw):
        mock_request = Mock(spec=httpx.Request)
        mock_response = Mock(spec=httpx.Response)
        raise httpx.HTTPStatusError("boom", request=mock_request, response=mock_response)

    class _Client3:
        async def request(self, *a, **kw):
            return await fake_request(*a, **kw)

    monkeypatch.setattr(APIClient, "_get_client", classmethod(lambda cls, timeout: _Client3()))
    APIClient.max_retries = 2
    with pytest.raises(UserServiceError):
        asyncio.run(APIClient._api_request("get", "http://x"))
