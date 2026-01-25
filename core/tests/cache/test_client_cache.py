import asyncio
import pytest

from core.cache.base import BaseCacheManager
from core.cache import Cache
from core.enums import Language, ProfileStatus
from core.schemas import Profile
from core.exceptions import ProfileNotFoundError

from unittest.mock import AsyncMock


def test_update_profile_uses_profile_key(monkeypatch):
    async def runner():
        called = {}

        async def fake_update_json(key, field, updates):
            called["field"] = field

        async def fake_set(key, field, value):
            called["field"] = field

        async def fake_get_profile(profile_id: int):
            return Profile(id=profile_id, tg_id=111, language=Language.ua, status=ProfileStatus.completed)

        monkeypatch.setattr(BaseCacheManager, "update_json", fake_update_json)
        monkeypatch.setattr(BaseCacheManager, "set", fake_set)
        monkeypatch.setattr("core.cache.profile.APIService.profile.get_profile", fake_get_profile)

        profile_id = 5
        await Cache.profile.update_record(profile_id, {"status": ProfileStatus.completed})
        assert called.get("field") == str(profile_id)

    asyncio.run(runner())


def test_get_profile_not_found(monkeypatch):
    async def runner():
        async def fake_get(_: int):
            return None

        monkeypatch.setattr(
            "core.cache.profile.APIService.profile.get_profile",
            AsyncMock(return_value=None),
        )
        with pytest.raises(ProfileNotFoundError):
            await Cache.profile.get_record(999)

    asyncio.run(runner())
