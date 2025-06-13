import json
from decimal import Decimal
from json import JSONDecodeError
from typing import Any, ClassVar

from loguru import logger
from redis.asyncio import Redis
from redis.exceptions import RedisError

from config.env_settings import settings


class BaseCacheManager:
    redis: ClassVar[Redis] = Redis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )

    @classmethod
    def _add_prefix(cls, key: str) -> str:
        return f"app:{key}"

    @staticmethod
    def _json_safe(data: dict[str, Any]) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        for k, v in data.items():
            if isinstance(v, Decimal):
                safe[k] = str(v)
            elif isinstance(v, dict):
                safe[k] = BaseCacheManager._json_safe(v)
            else:
                safe[k] = v
        return safe

    @classmethod
    async def close_pool(cls) -> None:
        try:
            await cls.redis.close()
            logger.info("Redis connection closed.")
        except Exception as e:
            logger.error(f"Error closing Redis connection: {e}")

    @classmethod
    async def healthcheck(cls) -> bool:
        try:
            return await cls.redis.ping()
        except Exception as e:
            logger.critical(f"Redis healthcheck failed: {e}")
            return False

    @classmethod
    async def get(cls, key: str, field: str) -> str | None:
        try:
            return await cls.redis.hget(cls._add_prefix(key), field)
        except RedisError as e:
            logger.error(f"Redis GET error [{key}:{field}]: {e}")
            return None

    @classmethod
    async def set(cls, key: str, field: str, value: str) -> None:
        try:
            await cls.redis.hset(cls._add_prefix(key), field, value)
        except RedisError as e:
            logger.error(f"Redis SET error [{key}:{field}]: {e}")

    @classmethod
    async def delete(cls, key: str, field: str) -> None:
        try:
            await cls.redis.hdel(cls._add_prefix(key), field)
        except RedisError as e:
            logger.error(f"Redis DELETE error [{key}:{field}]: {e}")

    @classmethod
    async def get_all(cls, key: str) -> dict[str, str]:
        try:
            return await cls.redis.hgetall(cls._add_prefix(key))
        except RedisError as e:
            logger.error(f"Redis HGETALL error [{key}]: {e}")
            return {}

    @classmethod
    async def get_json(cls, key: str, field: str) -> dict[str, Any] | None:
        raw = await cls.get(key, field)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (JSONDecodeError, TypeError) as e:
            logger.error(f"Invalid JSON [{key}:{field}]: {e}")
            return None

    @classmethod
    async def set_json(cls, key: str, field: str, data: dict[str, Any]) -> None:
        try:
            safe = cls._json_safe(data)
            await cls.set(key, field, json.dumps(safe))
        except RedisError as e:
            logger.error(f"Redis SET JSON error [{key}:{field}]: {e}")

    @classmethod
    async def update_json(cls, key: str, field: str, updates: dict[str, Any]) -> None:
        try:
            existing = await cls.get_json(key, field) or {}
            existing.update(updates)
            safe = cls._json_safe(existing)
            await cls.set_json(key, field, safe)
        except RedisError as e:
            logger.error(f"Redis UPDATE JSON error [{key}:{field}]: {e}")

    @classmethod
    async def _fetch_from_service(
        cls, cache_key: str, field: str, *, use_fallback: bool
    ) -> Any:
        """Retrieve data from the backing service.

        Subclasses must override this to fetch the required object and raise the
        appropriate `*NotFoundError` when the object does not exist or
        ``use_fallback`` is ``False``.
        """
        raise NotImplementedError

    @classmethod
    def _validate_data(cls, raw: str, cache_key: str, field: str) -> Any:
        """Validate and deserialize cached data.

        Subclasses must override this to convert ``raw`` to the desired object
        type or raise an exception if the cached data is corrupted.
        """
        raise NotImplementedError

    @classmethod
    def _prepare_for_cache(cls, data: Any, cache_key: str, field: str) -> Any:
        """Convert ``data`` into a JSON serialisable form for caching."""
        if hasattr(data, "model_dump"):
            return data.model_dump()
        return data

    @classmethod
    async def get_or_fetch(
        cls, cache_key: str, field: str, *, use_fallback: bool = True
    ) -> Any:
        """Retrieve an item from cache or fallback to the backing service."""

        raw = await cls.get(cache_key, field)
        if raw:
            try:
                return cls._validate_data(raw, cache_key, field)
            except Exception as e:  # pragma: no cover - best effort cleanup
                logger.debug(
                    f"Corrupt cache entry for {cache_key}:{field}: {e}"
                )
                await cls.delete(cache_key, field)

        data = await cls._fetch_from_service(cache_key, field, use_fallback=use_fallback)
        try:
            prepared = cls._prepare_for_cache(data, cache_key, field)
            await cls.set(cache_key, field, json.dumps(prepared))
        except Exception as e:  # pragma: no cover - caching failure shouldn't crash
            logger.error(f"Failed to cache {cache_key}:{field}: {e}")
        return data
