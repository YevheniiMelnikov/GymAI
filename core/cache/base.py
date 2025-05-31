import json
from decimal import Decimal
from json import JSONDecodeError
from typing import Any, ClassVar

from loguru import logger
from redis.asyncio import Redis
from redis.exceptions import RedisError

from config.env_settings import Settings


class BaseCacheManager:
    redis: ClassVar[Redis] = Redis.from_url(
        Settings.REDIS_URL,
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
