import os

import redis

os.environ["REDIS_URL"] = "redis://redis/0"

from unittest.mock import AsyncMock, MagicMock

import pytest

from common.user_service import UserService
from common.cache_manager import CacheManager


@pytest.fixture  # broken
def user_service(monkeypatch: pytest.MonkeyPatch) -> UserService:
    with monkeypatch.context() as m:
        m.setattr(redis, "from_url", AsyncMock())
        yield UserService(storage=CacheManager(os.getenv("REDIS_URL")))


@pytest.fixture  # broken
def profile_manager() -> CacheManager:
    manager = CacheManager(os.getenv("REDIS_URL"))
    manager.redis = MagicMock()
    return manager
