from collections.abc import Awaitable, Callable
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from bot.handlers.internal.auth import require_internal_auth
from config.app_settings import settings


class DummyTransport:
    def __init__(self, ip: str) -> None:
        self._ip = ip

    def get_extra_info(self, name: str) -> SimpleNamespace | tuple[str, int] | None:
        if name == "peername":
            return (self._ip, 12345)
        return None


async def _call(
    handler: Callable[[web.Request], Awaitable[web.Response]],
    request: web.Request,
) -> web.Response:
    return await handler(request)


@pytest.mark.asyncio
async def test_internal_auth_with_key_and_allowed_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", "secret")
    monkeypatch.setattr(settings, "API_KEY", "external")
    monkeypatch.setattr(settings, "INTERNAL_IP_ALLOWLIST", ["10.0.0.1"])

    @require_internal_auth
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    request = make_mocked_request(
        "POST",
        "/internal/tasks/ai_plan_ready/",
        headers={"X-Internal-Api-Key": "secret"},
        transport=DummyTransport("10.0.0.1"),
    )
    response = await _call(handler, request)
    assert response.status == 200


@pytest.mark.asyncio
async def test_internal_auth_rejects_wrong_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", "secret")
    monkeypatch.setattr(settings, "API_KEY", "external")
    monkeypatch.setattr(settings, "INTERNAL_IP_ALLOWLIST", ["10.0.0.1"])

    @require_internal_auth
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    request = make_mocked_request(
        "POST",
        "/internal/tasks/ai_plan_ready/",
        headers={"X-Internal-Api-Key": "wrong"},
        transport=DummyTransport("10.0.0.1"),
    )
    response = await _call(handler, request)
    assert response.status == 401


@pytest.mark.asyncio
async def test_internal_auth_without_key_uses_ip_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", None)
    monkeypatch.setattr(settings, "API_KEY", "external")
    monkeypatch.setattr(settings, "INTERNAL_IP_ALLOWLIST", ["10.0.0.1"])

    @require_internal_auth
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    request = make_mocked_request(
        "POST",
        "/internal/tasks/ai_plan_ready/",
        headers={},
        transport=DummyTransport("10.0.0.1"),
    )
    response = await _call(handler, request)
    assert response.status == 200


@pytest.mark.asyncio
async def test_internal_auth_authorization_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", None)
    monkeypatch.setattr(settings, "API_KEY", "external")
    monkeypatch.setattr(settings, "INTERNAL_IP_ALLOWLIST", ["10.0.0.1"])

    @require_internal_auth
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    request = make_mocked_request(
        "POST",
        "/internal/tasks/ai_plan_ready/",
        headers={"Authorization": "Api-Key external"},
        transport=DummyTransport("10.0.0.1"),
    )
    response = await _call(handler, request)
    assert response.status == 200


@pytest.mark.asyncio
async def test_internal_auth_allows_key_without_ip_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", "secret")
    monkeypatch.setattr(settings, "API_KEY", "external")
    monkeypatch.setattr(settings, "INTERNAL_IP_ALLOWLIST", ["10.0.0.1"])

    @require_internal_auth
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    request = make_mocked_request(
        "POST",
        "/internal/tasks/ai_plan_ready/",
        headers={"X-Internal-Api-Key": "secret"},
        transport=DummyTransport("10.0.0.9"),
    )
    response = await _call(handler, request)
    assert response.status == 200


@pytest.mark.asyncio
async def test_internal_auth_requires_ip_or_key_when_unsecured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", None)
    monkeypatch.setattr(settings, "API_KEY", "external")
    monkeypatch.setattr(settings, "INTERNAL_IP_ALLOWLIST", ["10.0.0.1"])

    @require_internal_auth
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    request = make_mocked_request(
        "POST",
        "/internal/tasks/ai_plan_ready/",
        headers={},
        transport=DummyTransport("10.0.0.9"),
    )
    response = await _call(handler, request)
    assert response.status == 401


@pytest.mark.asyncio
async def test_internal_auth_supports_cidr_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "INTERNAL_API_KEY", None)
    monkeypatch.setattr(settings, "API_KEY", "external")
    monkeypatch.setattr(settings, "INTERNAL_IP_ALLOWLIST", ["10.0.0.0/24"])

    @require_internal_auth
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    request = make_mocked_request(
        "POST",
        "/internal/tasks/ai_plan_ready/",
        headers={},
        transport=DummyTransport("10.0.0.55"),
    )
    response = await _call(handler, request)
    assert response.status == 200
