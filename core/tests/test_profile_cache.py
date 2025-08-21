from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.cache.profile import ProfileCacheManager
from core.enums import Language, ProfileRole
from core.exceptions import ProfileNotFoundError
from core.schemas import Profile


class DummyService:
    async def get_profile_by_tg_id(self, tg_id: int) -> Profile | None:
        if tg_id == 1:
            return Profile(id=1, role=ProfileRole.client, tg_id=tg_id, language=Language.eng)
        return None


async def dummy_provider() -> DummyService:
    return DummyService()


@pytest.mark.asyncio
async def test_fetch_from_service_handles_awaitable(monkeypatch: pytest.MonkeyPatch) -> None:
    container: SimpleNamespace = SimpleNamespace(profile_service=dummy_provider)
    monkeypatch.setattr("core.cache.profile.get_container", lambda: container)
    profile: Profile = await ProfileCacheManager._fetch_from_service("profiles", "1", use_fallback=True)
    assert profile.tg_id == 1


@pytest.mark.asyncio
async def test_fetch_from_service_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    container: SimpleNamespace = SimpleNamespace(profile_service=dummy_provider)
    monkeypatch.setattr("core.cache.profile.get_container", lambda: container)
    with pytest.raises(ProfileNotFoundError):
        await ProfileCacheManager._fetch_from_service("profiles", "2", use_fallback=True)
