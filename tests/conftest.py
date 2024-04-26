import os

import redis

os.environ["REDIS_URL"] = "redis://redis/0"

from unittest.mock import AsyncMock

import pytest

from common.user_service import UserProfileManager, UserService


@pytest.fixture
def user_service(monkeypatch) -> UserService:
    with monkeypatch.context() as m:
        m.setattr(redis, "from_url", AsyncMock())
        m.setattr(os, "getenv", lambda name, default=None: "redis://localhost:6379" if name == "REDIS_URL" else default)
        yield UserService(storage=UserProfileManager(os.getenv("REDIS_URL")))
