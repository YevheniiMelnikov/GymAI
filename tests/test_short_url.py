import aiohttp
import pytest

from core.utils.short_url import short_url


class _Resp:
    def __init__(self, status: int, text: str) -> None:
        self.status = status
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def text(self) -> str:
        return self._text


class _Session:
    def __init__(self, status: int, text: str) -> None:
        self._status = status
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get(self, url: str, params: dict[str, str]):
        return _Resp(self._status, self._text)


@pytest.mark.asyncio
async def test_short_url_success(monkeypatch):
    def _factory(*args, **kwargs):
        return _Session(200, "https://tinyurl.com/abc")

    monkeypatch.setattr(aiohttp, "ClientSession", _factory)
    result = await short_url("https://example.com")
    assert result == "https://tinyurl.com/abc"


@pytest.mark.asyncio
async def test_short_url_failure(monkeypatch):
    def _factory(*args, **kwargs):
        return _Session(500, "err")

    monkeypatch.setattr(aiohttp, "ClientSession", _factory)
    result = await short_url("https://example.com")
    assert result == "https://example.com"
