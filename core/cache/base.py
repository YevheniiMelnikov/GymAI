import json
from typing import Any
from loguru import logger
import redis
from json import JSONDecodeError

from config.env_settings import Settings


class BaseCacheManager:
    redis = redis.from_url(Settings.REDIS_URL, encoding="utf-8", decode_responses=True)

    @classmethod
    def _add_prefix(cls, key: str) -> str:
        return f"app/{key}"

    @classmethod
    def close_pool(cls) -> None:
        if cls.redis:
            cls.redis.close()

    @classmethod
    def get(cls, key: str, field: str) -> str | None:
        try:
            return cls.redis.hget(cls._add_prefix(key), field)
        except Exception as e:
            logger.error(f"Redis error on get({key}, {field}): {e}")
            return None

    @classmethod
    def set(cls, key: str, field: str, value: str) -> None:
        try:
            cls.redis.hset(cls._add_prefix(key), field, value)
        except Exception as e:
            logger.error(f"Redis error on set({key}, {field}): {e}")

    @classmethod
    def delete(cls, key: str, field: str) -> None:
        try:
            cls.redis.hdel(cls._add_prefix(key), field)
        except Exception as e:
            logger.error(f"Redis error on delete({key}, {field}): {e}")

    @classmethod
    def get_all(cls, key: str) -> dict[str, str]:
        try:
            return cls.redis.hgetall(cls._add_prefix(key))
        except Exception as e:
            logger.error(f"Redis error on get_all({key}): {e}")
            return {}

    @classmethod
    def get_json(cls, key: str, field: str) -> dict[str, Any] | None:
        raw = cls.get(key, field)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (JSONDecodeError, TypeError) as e:
            logger.error(f"Invalid JSON for {key}:{field}: {e}")
        except Exception as e:
            logger.error(f"Redis error on get_json({key}, {field}): {e}")
        return None

    @classmethod
    def set_json(cls, key: str, field: str, data: dict[str, Any]) -> None:
        try:
            cls.set(key, field, json.dumps(data))
        except Exception as e:
            logger.error(f"Redis error on set_json({key}, {field}): {e}")

    @classmethod
    def update_json_fields(cls, key: str, field: str, new_data: dict[str, Any], allowed_fields: list[str]) -> None:
        try:
            existing = cls.get_json(key, field) or {}
            for k in allowed_fields:
                if k in new_data:
                    existing[k] = new_data[k]
            cls.set_json(key, field, existing)
        except Exception as e:
            logger.error(f"Error updating fields for {key}:{field}: {e}")
