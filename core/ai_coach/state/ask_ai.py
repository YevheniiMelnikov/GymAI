"""Helpers for idempotent AI question delivery tracking."""

from dataclasses import dataclass
from typing import Final

from loguru import logger
from redis.asyncio import Redis
from redis.exceptions import RedisError

from config.app_settings import settings
from core.utils.redis_lock import get_redis_client_for_db

AI_QUESTION_CLAIM_KEY: Final[str] = "ai:ask:claim:{request_id}"
AI_QUESTION_TASK_CLAIM_KEY: Final[str] = "ai:ask:task:{request_id}"
AI_QUESTION_DELIVERED_KEY: Final[str] = "ai:ask:delivered:{request_id}"
AI_QUESTION_FAILED_KEY: Final[str] = "ai:ask:failed:{request_id}"
AI_QUESTION_CHARGED_KEY: Final[str] = "ai:ask:charged:{request_id}"


@dataclass(slots=True)
class AiQuestionState:
    client: Redis

    @classmethod
    def create(cls) -> "AiQuestionState":
        return cls(get_redis_client_for_db(settings.AI_COACH_REDIS_STATE_DB))

    async def claim_delivery(self, request_id: str, ttl_s: int | None = None) -> bool:
        ttl = ttl_s or settings.AI_QA_DEDUP_TTL
        key = AI_QUESTION_CLAIM_KEY.format(request_id=request_id)
        try:
            result = await self.client.set(key, "1", nx=True, ex=ttl)
            return bool(result)
        except RedisError as exc:
            logger.warning(f"ai_question_claim_skip request_id={request_id} error={exc!s}")
            return True

    async def claim_task(self, request_id: str, ttl_s: int | None = None) -> bool:
        ttl = ttl_s or settings.AI_QA_DEDUP_TTL
        key = AI_QUESTION_TASK_CLAIM_KEY.format(request_id=request_id)
        try:
            result = await self.client.set(key, "1", nx=True, ex=ttl)
            return bool(result)
        except RedisError as exc:
            logger.warning(f"ai_question_task_claim_skip request_id={request_id} error={exc!s}")
            return True

    async def mark_delivered(self, request_id: str, ttl_s: int | None = None) -> None:
        ttl = ttl_s or settings.AI_QA_DEDUP_TTL
        key = AI_QUESTION_DELIVERED_KEY.format(request_id=request_id)
        try:
            await self.client.set(key, "1", ex=ttl)
        except RedisError as exc:
            logger.warning(f"ai_question_mark_delivered_failed request_id={request_id} error={exc!s}")

    async def mark_failed(self, request_id: str, reason: str, ttl_s: int | None = None) -> bool:
        ttl = ttl_s or settings.AI_QA_DEDUP_TTL
        key = AI_QUESTION_FAILED_KEY.format(request_id=request_id)
        try:
            result = await self.client.set(key, reason, ex=ttl, nx=True)
            if result:
                return True
        except RedisError as exc:
            logger.warning(f"ai_question_mark_failed_failed request_id={request_id} error={exc!s}")
        return False

    async def is_delivered(self, request_id: str) -> bool:
        key = AI_QUESTION_DELIVERED_KEY.format(request_id=request_id)
        try:
            result = await self.client.exists(key)
            return bool(result)
        except RedisError as exc:
            logger.warning(f"ai_question_is_delivered_skip request_id={request_id} error={exc!s}")
            return False

    async def is_failed(self, request_id: str) -> bool:
        key = AI_QUESTION_FAILED_KEY.format(request_id=request_id)
        try:
            result = await self.client.exists(key)
            return bool(result)
        except RedisError as exc:
            logger.warning(f"ai_question_is_failed_skip request_id={request_id} error={exc!s}")
            return False

    async def mark_charged(self, request_id: str, ttl_s: int | None = None) -> bool:
        ttl = ttl_s or settings.AI_QA_DEDUP_TTL
        key = AI_QUESTION_CHARGED_KEY.format(request_id=request_id)
        try:
            result = await self.client.set(key, "1", nx=True, ex=ttl)
            return bool(result)
        except RedisError as exc:
            logger.warning(f"ai_question_mark_charged_failed request_id={request_id} error={exc!s}")
            return True

    async def is_charged(self, request_id: str) -> bool:
        key = AI_QUESTION_CHARGED_KEY.format(request_id=request_id)
        try:
            result = await self.client.exists(key)
            return bool(result)
        except RedisError as exc:
            logger.warning(f"ai_question_is_charged_skip request_id={request_id} error={exc!s}")
            return False

    async def unmark_charged(self, request_id: str) -> bool:
        key = AI_QUESTION_CHARGED_KEY.format(request_id=request_id)
        try:
            result = await self.client.delete(key)
            return bool(result)
        except RedisError as exc:
            logger.warning(f"ai_question_unmark_charged_failed request_id={request_id} error={exc!s}")
            return False

    async def clear(self, request_id: str) -> None:
        keys = [
            AI_QUESTION_CLAIM_KEY.format(request_id=request_id),
            AI_QUESTION_TASK_CLAIM_KEY.format(request_id=request_id),
            AI_QUESTION_DELIVERED_KEY.format(request_id=request_id),
            AI_QUESTION_FAILED_KEY.format(request_id=request_id),
            AI_QUESTION_CHARGED_KEY.format(request_id=request_id),
        ]
        try:
            await self.client.delete(*keys)
        except RedisError as exc:
            logger.warning(f"ai_question_clear_failed request_id={request_id} error={exc!s}")
