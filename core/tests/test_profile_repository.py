import types

import pytest  # pyrefly: ignore[import-error]

from core.infra.profile_repository import HTTPProfileRepository


class _Profile:
    @classmethod
    def model_validate(cls, data: dict) -> types.SimpleNamespace:
        return types.SimpleNamespace(**data)


def _settings() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        API_URL="http://api/",
        API_KEY="key",
        API_MAX_RETRIES=1,
        API_RETRY_INITIAL_DELAY=0,
        API_RETRY_BACKOFF_FACTOR=1,
        API_RETRY_MAX_DELAY=0,
        API_TIMEOUT=5,
    )


class _Client:
    pass


@pytest.mark.asyncio
async def test_get_profile_success(monkeypatch):
    monkeypatch.setattr("core.infra.profile_repository.Profile", _Profile)
    repo = HTTPProfileRepository(_Client(), _settings())  # pyrefly: ignore[bad-argument-type]

    async def fake_request(method, url, data=None, headers=None):
        return 200, {"id": 1, "tg_id": 2, "role": "user", "language": "eng"}

    monkeypatch.setattr(repo, "_api_request", fake_request)
    profile = await repo.get_profile(1)
    assert profile is not None
    assert profile.id == 1


@pytest.mark.asyncio
async def test_get_profile_not_found(monkeypatch):
    monkeypatch.setattr("core.infra.profile_repository.Profile", _Profile)
    repo = HTTPProfileRepository(_Client(), _settings())  # pyrefly: ignore[bad-argument-type]

    async def fake_request(method, url, data=None, headers=None):
        return 404, None

    monkeypatch.setattr(repo, "_api_request", fake_request)
    profile = await repo.get_profile(1)
    assert profile is None
