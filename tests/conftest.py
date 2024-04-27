import os

import redis

os.environ["REDIS_URL"] = "redis://redis/0"

from unittest.mock import AsyncMock, MagicMock

import pytest

from common.user_service import UserProfileManager, UserService


@pytest.fixture
def user_service(monkeypatch) -> UserService:
    with monkeypatch.context() as m:
        m.setattr(redis, "from_url", AsyncMock())
        yield UserService(storage=UserProfileManager(os.getenv("REDIS_URL")))


@pytest.fixture
def profile_manager() -> UserProfileManager:
    manager = UserProfileManager(os.getenv("REDIS_URL"))
    manager.redis = MagicMock()
    return manager
