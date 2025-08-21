from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.services.internal import APIService


class DummyService:
    async def ping(self, value: int) -> int:
        return value + 1


async def dummy_provider() -> DummyService:
    return DummyService()


@pytest.mark.asyncio
async def test_api_service_proxy_resolves_awaitable_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    container = SimpleNamespace(profile_service=dummy_provider)
    monkeypatch.setattr(APIService, "_provider", lambda: container)
    assert await APIService.profile.ping(1) == 2


@pytest.mark.asyncio
async def test_api_service_proxy_resolves_sync_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    container = SimpleNamespace(profile_service=DummyService)
    monkeypatch.setattr(APIService, "_provider", lambda: container)
    assert await APIService.profile.ping(2) == 3
