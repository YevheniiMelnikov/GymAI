import logging

import json
from hashlib import sha256
from typing import Any, Awaitable, Iterable, Mapping, cast

from redis.asyncio import Redis

from ai_coach.agent.knowledge.utils.text import normalize_text
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
    @staticmethod
    def _normalize_metadata(hash_value: str, metadata: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if metadata is None:
            return None
        payload = dict(metadata)
        payload.setdefault("digest_sha", hash_value)
        return payload

    @classmethod
    async def add(cls, dataset: str, hash_value: str, metadata: Mapping[str, Any] | None = None) -> None:
        try:
            key = cls._key(dataset)
            await cast(Awaitable[int], cls.redis.sadd(key, hash_value))
            await cast(
                Awaitable[int],
                cls.redis.expire(key, settings.BACKUP_RETENTION_DAYS * 24 * 60 * 60),
            )
            normalized_meta = cls._normalize_metadata(hash_value, metadata)
            meta_bytes = 0
            if normalized_meta:
                meta_key = cls._meta_key(dataset)
                json_meta = json.dumps(normalized_meta)
                meta_bytes = len(json_meta.encode("utf-8"))
                await cast(Awaitable[int], cls.redis.hset(meta_key, hash_value, json_meta))
                await cast(
                    Awaitable[int],
                    cls.redis.expire(meta_key, settings.BACKUP_RETENTION_DAYS * 24 * 60 * 60),
                )
            logger.debug(f"[hashstore_put] sha={hash_value[:12]} bytes={meta_bytes} dataset={dataset} ok")
        except Exception as e:  # pragma: no cover - best effort
            logger.error(f"HashStore.add error {dataset}: {e}")
            logger.debug(f"[hashstore_put] sha={hash_value[:12]} bytes=0 dataset={dataset} err={e}")

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
        normalized = normalize_text(text)
        if not normalized:
            return None
        digest = sha256(normalized.encode()).hexdigest()
        return await cls.metadata(dataset, digest)

    @classmethod
    async def list(cls, dataset: str) -> set[str]:
        try:
            members = await cast(Awaitable[Iterable[str]], cls.redis.smembers(cls._key(dataset)))
        except Exception as e:  # pragma: no cover - best effort
            logger.error(f"HashStore.list error {dataset}: {e}")
            return set()
        return {str(item) for item in members}

    @classmethod
    async def list_all_datasets(cls) -> set[str]:
        try:
            keys = await cast(Awaitable[Iterable[str]], cls.redis.keys("cognee_hashes:*"))
            return {key.removeprefix("cognee_hashes:") for key in keys}
        except Exception as e:  # pragma: no cover - best effort
            logger.error(f"HashStore.list_all_datasets error: {e}")
            return set()
