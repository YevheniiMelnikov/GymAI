import logging

from typing import Awaitable, cast
from redis.asyncio import Redis

from config.app_settings import settings


logger = logging.getLogger(__name__)


class HashStore:
    """Persist SHA256 hashes for deduplication."""

    redis: Redis = Redis.from_url(
        url=settings.REDIS_URL,
        db=2,
        encoding="utf-8",
        decode_responses=True,
    )

    @staticmethod
    def _key(dataset: str) -> str:
        return f"cognee_hashes:{dataset}"

    @classmethod
    async def contains(cls, dataset: str, hash_value: str) -> bool:
        try:
            return bool(await cast(Awaitable[int], cls.redis.sismember(cls._key(dataset), hash_value)))
        except Exception as e:  # pragma: no cover - best effort
            logger.error(f"HashStore.contains error {dataset}: {e}")
            return False

    @classmethod
    async def add(cls, dataset: str, hash_value: str) -> None:
        try:
            key = cls._key(dataset)
            await cast(Awaitable[int], cls.redis.sadd(key, hash_value))
            await cast(
                Awaitable[int],
                cls.redis.expire(key, settings.BACKUP_RETENTION_DAYS * 24 * 60 * 60),
            )
        except Exception as e:  # pragma: no cover - best effort
            logger.error(f"HashStore.add error {dataset}: {e}")

    @classmethod
    async def clear(cls, dataset: str) -> None:
        try:
            await cast(Awaitable[int], cls.redis.delete(cls._key(dataset)))
        except Exception as e:  # pragma: no cover - best effort
            logger.error(f"HashStore.clear error {dataset}: {e}")
