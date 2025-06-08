import httpx
import pytest
import importlib.util
from pathlib import Path

from core.exceptions import UserServiceError

spec = importlib.util.spec_from_file_location(
    "api_client", Path(__file__).resolve().parents[1] / "services" / "api_client.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)  # type: ignore[arg-type]
APIClient = module.APIClient


class DummyResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.request = httpx.Request("GET", "http://test")

    @property
    def is_success(self):
        return 200 <= self.status_code < 300

    def json(self):
        if self._json is None:
            raise httpx.DecodingError("no json")
        return self._json


def test_api_request_success(monkeypatch):
    import asyncio
    async def fake_request(*a, **kw):
        return DummyResponse(200, {"ok": True})

    monkeypatch.setattr(APIClient, "client", type("C", (), {"request": fake_request})())
    code, data = asyncio.run(APIClient._api_request("get", "http://x"))
    assert code == 200
    assert data == {"ok": True}


def test_api_request_retries(monkeypatch):
    import asyncio
    calls = []

    async def fake_request(*a, **kw):
        calls.append(1)
        if len(calls) < 2:
            raise httpx.HTTPStatusError("boom", request=None, response=None)
        return DummyResponse(200, {"ok": True})

    monkeypatch.setattr(APIClient, "client", type("C", (), {"request": fake_request})())
    code, _ = asyncio.run(APIClient._api_request("get", "http://x"))
    assert len(calls) == 2
    assert code == 200


def test_api_request_gives_up(monkeypatch):
    import asyncio
    async def fake_request(*a, **kw):
        raise httpx.HTTPStatusError("boom", request=None, response=None)

    monkeypatch.setattr(APIClient, "client", type("C", (), {"request": fake_request})())
    APIClient.max_retries = 2
    with pytest.raises(UserServiceError):
        asyncio.run(APIClient._api_request("get", "http://x"))

