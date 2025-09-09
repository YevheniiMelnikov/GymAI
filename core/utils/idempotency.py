from typing import Optional

from loguru import logger
from redis.asyncio import Redis, from_url
from redis.exceptions import RedisError

from config.app_settings import settings

_redis: Optional[Redis] = None


async def _get_redis() -> Optional[Redis]:
    global _redis
    if _redis is None:
        url = settings.REDIS_URL
        if not url:
            logger.warning("REDIS_URL not set, idempotency disabled")
            return None
        _redis = from_url(url, encoding="utf-8", decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is None:
        return
    try:
        await _redis.close()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Redis close failed: {exc}")
    finally:
        _redis = None


async def acquire_once(key: str, ttl: int = 300) -> bool:
    redis = await _get_redis()
    if redis is None:
        logger.warning("Idempotency skipped: redis unavailable")
        return True
    try:
        return bool(await redis.set(f"idemp:{key}", "1", nx=True, ex=ttl))
    except RedisError as exc:
        logger.warning(f"Idempotency check failed: {exc}")
        return True
