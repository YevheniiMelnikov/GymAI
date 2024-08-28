import os

import pytest
import redis

os.environ["REDIS_URL"] = "redis://redis/0"

from unittest.mock import AsyncMock, MagicMock

from common.backend_service import BackendService
from common.cache_manager import CacheManager


@pytest.fixture  # broken
def backend_service(monkeypatch: pytest.MonkeyPatch) -> BackendService:
    with monkeypatch.context() as m:
        m.setattr(redis, "from_url", AsyncMock())
        yield BackendService(storage=CacheManager(os.getenv("REDIS_URL")))


@pytest.fixture  # broken
def profile_manager() -> CacheManager:
    manager = CacheManager(os.getenv("REDIS_URL"))
    manager.redis = MagicMock()
    return manager
