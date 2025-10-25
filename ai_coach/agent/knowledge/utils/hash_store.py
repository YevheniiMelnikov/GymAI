import logging

import json
from hashlib import sha256
from typing import Any, Awaitable, Mapping, cast

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

    @staticmethod
    def _meta_key(dataset: str) -> str:
        return f"cognee_hash_meta:{dataset}"

    @classmethod
    async def contains(cls, dataset: str, hash_value: str) -> bool:
        try:
            return bool(await cast(Awaitable[int], cls.redis.sismember(cls._key(dataset), hash_value)))
        except Exception as e:  # pragma: no cover - best effort
            logger.error(f"HashStore.contains error {dataset}: {e}")
            return False

    @classmethod
    async def add(
        cls,
        dataset: str,
        hash_value: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        try:
            key = cls._key(dataset)
            await cast(Awaitable[int], cls.redis.sadd(key, hash_value))
            await cast(
                Awaitable[int],
                cls.redis.expire(key, settings.BACKUP_RETENTION_DAYS * 24 * 60 * 60),
            )
            if metadata:
                await cast(
                    Awaitable[int],
                    cls.redis.hset(cls._meta_key(dataset), hash_value, json.dumps(metadata)),
                )
        except Exception as e:  # pragma: no cover - best effort
            logger.error(f"HashStore.add error {dataset}: {e}")

    @classmethod
    async def clear(cls, dataset: str) -> None:
        try:
            await cast(Awaitable[int], cls.redis.delete(cls._key(dataset)))
            await cast(Awaitable[int], cls.redis.delete(cls._meta_key(dataset)))
        except Exception as e:  # pragma: no cover - best effort
            logger.error(f"HashStore.clear error {dataset}: {e}")

    @classmethod
    async def metadata(cls, dataset: str, hash_value: str) -> dict[str, Any] | None:
        try:
            raw = await cast(Awaitable[str | None], cls.redis.hget(cls._meta_key(dataset), hash_value))
        except Exception as e:  # pragma: no cover - best effort
            logger.error(f"HashStore.metadata error {dataset}: {e}")
            return None
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"HashStore.metadata decode_failed dataset={dataset}")
            return None
        if not isinstance(data, dict):
            return None
        return data

    @classmethod
    async def metadata_for_text(cls, dataset: str, text: str) -> dict[str, Any] | None:
        digest = sha256(text.encode()).hexdigest()
        return await cls.metadata(dataset, digest)
