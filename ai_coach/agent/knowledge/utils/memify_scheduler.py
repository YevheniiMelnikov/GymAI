from config.app_settings import settings
from core.ai_coach import memify_scheduler as core_memify_scheduler
from core.utils.redis_lock import get_redis_client

__all__ = [
    "get_redis_client",
    "schedule_profile_memify",
    "schedule_profile_memify_sync",
    "settings",
    "try_lock_chat_summary",
]


async def schedule_profile_memify(
    profile_id: int,
    *,
    reason: str = "paid_flow",
    delay_s: float | int | None = None,
) -> bool:
    core_memify_scheduler.settings = settings
    core_memify_scheduler.get_redis_client = get_redis_client
    return await core_memify_scheduler.schedule_profile_memify(profile_id, reason=reason, delay_s=delay_s)


def schedule_profile_memify_sync(
    profile_id: int,
    *,
    reason: str = "paid_flow",
    delay_s: float | int | None = None,
) -> bool:
    core_memify_scheduler.settings = settings
    core_memify_scheduler.get_redis_client = get_redis_client
    return core_memify_scheduler.schedule_profile_memify_sync(profile_id, reason=reason, delay_s=delay_s)


async def try_lock_chat_summary(profile_id: int, ttl_seconds: int) -> bool:
    core_memify_scheduler.get_redis_client = get_redis_client
    return await core_memify_scheduler.try_lock_chat_summary(profile_id, ttl_seconds)
