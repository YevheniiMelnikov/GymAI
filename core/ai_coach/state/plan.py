"""Helpers for idempotent AI plan delivery tracking."""

from dataclasses import dataclass
from typing import Final

from loguru import logger
from redis.asyncio import Redis
from redis.exceptions import RedisError

from config.app_settings import settings
from core.utils.redis_lock import get_redis_client

AI_PLAN_CLAIM_KEY: Final[str] = "ai:plan:claim:{plan_id}"
AI_PLAN_DELIVERED_KEY: Final[str] = "ai:plan:delivered:{plan_id}"
AI_PLAN_FAILED_KEY: Final[str] = "ai:plan:failed:{plan_id}"


@dataclass(slots=True)
class AiPlanState:
    """Atomic Redis-based helpers for AI plan delivery state."""

    client: Redis

    @classmethod
    def create(cls) -> "AiPlanState":
        return cls(get_redis_client())

    async def claim_delivery(self, plan_id: str, ttl_s: int | None = None) -> bool:
        ttl = ttl_s or settings.AI_PLAN_DEDUP_TTL
        key = AI_PLAN_CLAIM_KEY.format(plan_id=plan_id)
        try:
            result = await self.client.set(key, "1", nx=True, ex=ttl)
            return bool(result)
        except RedisError as exc:
            logger.warning(f"ai_plan_state_claim_skip plan_id={plan_id} error={exc!s}")
            return True

    async def mark_delivered(self, plan_id: str, ttl_s: int | None = None) -> None:
        ttl = ttl_s or settings.AI_PLAN_DEDUP_TTL
        key = AI_PLAN_DELIVERED_KEY.format(plan_id=plan_id)
        try:
            await self.client.set(key, "1", ex=ttl)
        except RedisError as exc:
            logger.warning(f"ai_plan_state_mark_delivered_failed plan_id={plan_id} error={exc!s}")

    async def mark_failed(self, plan_id: str, reason: str, ttl_s: int | None = None) -> bool:
        ttl = ttl_s or settings.AI_PLAN_NOTIFY_FAILURE_TTL
        key = AI_PLAN_FAILED_KEY.format(plan_id=plan_id)
        try:
            result = await self.client.set(key, reason, ex=ttl, nx=True)
            if result:
                return True
        except RedisError as exc:
            logger.warning(f"ai_plan_state_mark_failed_failed plan_id={plan_id} error={exc!s}")
        return False

    async def is_delivered(self, plan_id: str) -> bool:
        key = AI_PLAN_DELIVERED_KEY.format(plan_id=plan_id)
        try:
            result = await self.client.exists(key)
            return bool(result)
        except RedisError as exc:
            logger.warning(f"ai_plan_state_is_delivered_skip plan_id={plan_id} error={exc!s}")
            return False

    async def is_failed(self, plan_id: str) -> bool:
        key = AI_PLAN_FAILED_KEY.format(plan_id=plan_id)
        try:
            result = await self.client.exists(key)
            return bool(result)
        except RedisError as exc:
            logger.warning(f"ai_plan_state_is_failed_skip plan_id={plan_id} error={exc!s}")
            return False
