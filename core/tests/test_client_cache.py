import asyncio
import pytest

from core.cache.base import BaseCacheManager
from core.cache import Cache
from core.enums import ClientStatus


def test_update_client_uses_profile_key(monkeypatch):
    async def runner():
        called = {}

        async def fake_update_json(key, field, updates):
            called["field"] = field

        async def fake_set(key, field, value):
            called["field"] = field

        monkeypatch.setattr(BaseCacheManager, "update_json", fake_update_json)
        monkeypatch.setattr(BaseCacheManager, "set", fake_set)

        profile_id = 5
        await Cache.client.update_client(profile_id, {"status": ClientStatus.default})
        assert called.get("field") == str(profile_id)

    asyncio.run(runner())


def test_get_client_not_found(monkeypatch):
    async def runner():
        async def fake_get(_: int):
            return None

        monkeypatch.setattr(Cache.client.service, "get_client_by_profile_id", fake_get)
        with pytest.raises(Exception):
            await Cache.client.get_client(999)

    asyncio.run(runner())
