"""Helpers for idempotent AI diet delivery tracking."""

from dataclasses import dataclass
from typing import Final

from loguru import logger
from redis.asyncio import Redis
from redis.exceptions import RedisError

from config.app_settings import settings
from core.utils.redis_lock import get_redis_client_for_db

AI_DIET_CLAIM_KEY: Final[str] = "ai:diet:claim:{request_id}"
AI_DIET_TASK_CLAIM_KEY: Final[str] = "ai:diet:task:{request_id}"
AI_DIET_DELIVERED_KEY: Final[str] = "ai:diet:delivered:{request_id}"
AI_DIET_FAILED_KEY: Final[str] = "ai:diet:failed:{request_id}"
AI_DIET_CHARGED_KEY: Final[str] = "ai:diet:charged:{request_id}"
AI_DIET_REFUND_LOCK_KEY: Final[str] = "ai:diet:refund_lock:{request_id}"
AI_DIET_REFUNDED_KEY: Final[str] = "ai:diet:refunded:{request_id}"


@dataclass(slots=True)
class AiDietState:
    client: Redis

    @classmethod
    def create(cls) -> "AiDietState":
        return cls(get_redis_client_for_db(settings.AI_COACH_REDIS_STATE_DB))

    async def claim_delivery(self, request_id: str, ttl_s: int | None = None) -> bool:
        ttl = ttl_s or settings.AI_QA_DEDUP_TTL
        key = AI_DIET_CLAIM_KEY.format(request_id=request_id)
        try:
            result = await self.client.set(key, "1", nx=True, ex=ttl)
            return bool(result)
        except RedisError as exc:
            logger.warning(f"ai_diet_claim_skip request_id={request_id} error={exc!s}")
            return True

    async def claim_task(self, request_id: str, ttl_s: int | None = None) -> bool:
        ttl = ttl_s or settings.AI_QA_DEDUP_TTL
        key = AI_DIET_TASK_CLAIM_KEY.format(request_id=request_id)
        try:
            result = await self.client.set(key, "1", nx=True, ex=ttl)
            return bool(result)
        except RedisError as exc:
            logger.warning(f"ai_diet_task_claim_skip request_id={request_id} error={exc!s}")
            return True

    async def mark_delivered(self, request_id: str, ttl_s: int | None = None) -> None:
        ttl = ttl_s or settings.AI_QA_DEDUP_TTL
        key = AI_DIET_DELIVERED_KEY.format(request_id=request_id)
        try:
            await self.client.set(key, "1", ex=ttl)
        except RedisError as exc:
            logger.warning(f"ai_diet_mark_delivered_failed request_id={request_id} error={exc!s}")

    async def mark_failed(self, request_id: str, reason: str, ttl_s: int | None = None) -> bool:
        ttl = ttl_s or settings.AI_QA_DEDUP_TTL
        key = AI_DIET_FAILED_KEY.format(request_id=request_id)
        try:
            result = await self.client.set(key, reason, ex=ttl, nx=True)
            if result:
                return True
        except RedisError as exc:
            logger.warning(f"ai_diet_mark_failed_failed request_id={request_id} error={exc!s}")
        return False

    async def is_delivered(self, request_id: str) -> bool:
        key = AI_DIET_DELIVERED_KEY.format(request_id=request_id)
        try:
            result = await self.client.exists(key)
            return bool(result)
        except RedisError as exc:
            logger.warning(f"ai_diet_is_delivered_skip request_id={request_id} error={exc!s}")
            return False

    async def is_failed(self, request_id: str) -> bool:
        key = AI_DIET_FAILED_KEY.format(request_id=request_id)
        try:
            result = await self.client.exists(key)
            return bool(result)
        except RedisError as exc:
            logger.warning(f"ai_diet_is_failed_skip request_id={request_id} error={exc!s}")
            return False

    async def mark_charged(self, request_id: str, ttl_s: int | None = None) -> bool:
        ttl = ttl_s or settings.AI_QA_DEDUP_TTL
        key = AI_DIET_CHARGED_KEY.format(request_id=request_id)
        try:
            result = await self.client.set(key, "1", nx=True, ex=ttl)
            return bool(result)
        except RedisError as exc:
            logger.warning(f"ai_diet_mark_charged_failed request_id={request_id} error={exc!s}")
            return False

    async def is_charged(self, request_id: str) -> bool:
        key = AI_DIET_CHARGED_KEY.format(request_id=request_id)
        try:
            result = await self.client.exists(key)
            return bool(result)
        except RedisError as exc:
            logger.warning(f"ai_diet_is_charged_failed request_id={request_id} error={exc!s}")
            raise

    async def unmark_charged(self, request_id: str) -> bool:
        key = AI_DIET_CHARGED_KEY.format(request_id=request_id)
        try:
            result = await self.client.delete(key)
            return bool(result)
        except RedisError as exc:
            logger.warning(f"ai_diet_unmark_charged_failed request_id={request_id} error={exc!s}")
            raise

    async def claim_refund(self, request_id: str, ttl_s: int | None = None) -> bool:
        ttl = ttl_s or settings.AI_QA_DEDUP_TTL
        key = AI_DIET_REFUND_LOCK_KEY.format(request_id=request_id)
        try:
            result = await self.client.set(key, "1", nx=True, ex=ttl)
            return bool(result)
        except RedisError as exc:
            logger.warning(f"ai_diet_refund_lock_failed request_id={request_id} error={exc!s}")
            raise

    async def release_refund_lock(self, request_id: str) -> None:
        key = AI_DIET_REFUND_LOCK_KEY.format(request_id=request_id)
        try:
            await self.client.delete(key)
        except RedisError as exc:
            logger.warning(f"ai_diet_refund_lock_release_failed request_id={request_id} error={exc!s}")

    async def mark_refunded(self, request_id: str, ttl_s: int | None = None) -> bool:
        ttl = ttl_s or settings.AI_QA_DEDUP_TTL
        key = AI_DIET_REFUNDED_KEY.format(request_id=request_id)
        try:
            result = await self.client.set(key, "1", ex=ttl, nx=True)
            return bool(result)
        except RedisError as exc:
            logger.warning(f"ai_diet_mark_refunded_failed request_id={request_id} error={exc!s}")
            raise

    async def is_refunded(self, request_id: str) -> bool:
        key = AI_DIET_REFUNDED_KEY.format(request_id=request_id)
        try:
            result = await self.client.exists(key)
            return bool(result)
        except RedisError as exc:
            logger.warning(f"ai_diet_is_refunded_failed request_id={request_id} error={exc!s}")
            raise

    async def clear(self, request_id: str) -> None:
        keys = [
            AI_DIET_CLAIM_KEY.format(request_id=request_id),
            AI_DIET_TASK_CLAIM_KEY.format(request_id=request_id),
            AI_DIET_DELIVERED_KEY.format(request_id=request_id),
            AI_DIET_FAILED_KEY.format(request_id=request_id),
            AI_DIET_CHARGED_KEY.format(request_id=request_id),
            AI_DIET_REFUND_LOCK_KEY.format(request_id=request_id),
            AI_DIET_REFUNDED_KEY.format(request_id=request_id),
        ]
        try:
            await self.client.delete(*keys)
        except RedisError as exc:
            logger.warning(f"ai_diet_clear_failed request_id={request_id} error={exc!s}")
