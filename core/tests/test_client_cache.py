import pytest
import fakeredis

from core.cache.base import BaseCacheManager
from core.cache import Cache
from core.enums import ClientStatus
from core.schemas import Client

@pytest.fixture(autouse=True)
async def fake_redis(monkeypatch):
    yield

@pytest.mark.asyncio
async def test_update_client_uses_profile_key(monkeypatch):
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


@pytest.mark.asyncio
async def test_get_client_not_found(monkeypatch):
    async def fake_get(_: int):
        return None
    monkeypatch.setattr(Cache.client.service, "get_client_by_profile_id", fake_get)
    with pytest.raises(Exception):
        await Cache.client.get_client(999)
