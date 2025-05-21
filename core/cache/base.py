import json
from typing import Any, ClassVar
from loguru import logger
from redis.asyncio import Redis
from redis.exceptions import RedisError
from json import JSONDecodeError

from config.env_settings import Settings


class BaseCacheManager:
    redis: ClassVar[Redis] = Redis.from_url(
        Settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )

    @classmethod
    async def healthcheck(cls) -> bool:
        try:
            return await cls.redis.ping()
        except Exception as e:
            logger.critical(f"Redis healthcheck failed: {e}")
            return False

    @classmethod
    def _add_prefix(cls, key: str) -> str:
        return f"app:{key}"

    @classmethod
    async def close_pool(cls) -> None:
        try:
            await cls.redis.close()
            logger.info("Redis connection closed.")
        except Exception as e:
            logger.error(f"Error closing Redis connection: {e}")

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
            await cls.set(key, field, json.dumps(data))
        except RedisError as e:
            logger.error(f"Redis SET JSON error [{key}:{field}]: {e}")

    @classmethod
    async def update_json(cls, key: str, field: str, updates: dict[str, Any]) -> None:
        try:
            existing = await cls.get_json(key, field) or {}
            existing.update(updates)
            await cls.set_json(key, field, existing)
        except RedisError as e:
            logger.error(f"Redis UPDATE JSON error [{key}:{field}]: {e}")
