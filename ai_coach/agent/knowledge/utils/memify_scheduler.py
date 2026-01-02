import asyncio
import time

from loguru import logger

from config.app_settings import settings
from core.ai_coach import (
    memify_run_at_key,
    memify_schedule_ttl,
    memify_scheduled_key,
)
from core.utils.redis_lock import get_redis_client


def _dataset_labels(profile_id: int) -> str:
    return f"kb_profile_{profile_id},kb_chat_{profile_id}"


async def schedule_profile_memify(
    profile_id: int,
    *,
    reason: str = "paid_flow",
    delay_s: float | int | None = None,
) -> bool:
    """
    Schedule a delayed memify for profile datasets with cross-process dedup.
    Returns True if a task was enqueued.
    """
    env_mode = str(getattr(settings, "ENVIRONMENT", "development")).lower()
    if env_mode != "production":
        logger.info(f"memify_schedule_skipped profile_id={profile_id} reason=non_production environment={env_mode}")
        return False
    delay_value = float(delay_s if delay_s is not None else settings.AI_COACH_MEMIFY_DELAY_SECONDS)
    countdown = max(delay_value, 0.0)
    run_at = time.time() + countdown
    ttl = memify_schedule_ttl(countdown)
    scheduled_key = memify_scheduled_key(profile_id)
    run_at_key = memify_run_at_key(profile_id)
    datasets = _dataset_labels(profile_id)
    try:
        client = get_redis_client()
        await client.set(run_at_key, f"{run_at}", ex=ttl)
        already_scheduled = not await client.set(scheduled_key, "1", nx=True, ex=ttl)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"memify_schedule_dedupe_failed profile_id={profile_id} detail={exc}")
        return False
    if already_scheduled:
        await client.set(scheduled_key, "1", ex=ttl)
        logger.info(
            f"memify_schedule_skipped profile_id={profile_id} datasets={datasets} reason=dedupe_hit delay_s={countdown}"
        )
        return False

    try:
        from core.tasks.ai_coach.maintenance import memify_profile_datasets

        task = memify_profile_datasets.apply_async(
            kwargs={"profile_id": profile_id, "reason": reason},
            countdown=countdown,
        )
        logger.info(
            f"memify_schedule_enqueued profile_id={profile_id} datasets={datasets} "
            f"reason={reason} delay_s={countdown} task_id={getattr(task, 'id', 'unknown')}"
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"memify_schedule_failed profile_id={profile_id} detail={exc}")
        return False


def schedule_profile_memify_sync(
    profile_id: int,
    *,
    reason: str = "paid_flow",
    delay_s: float | int | None = None,
) -> bool:
    """Sync wrapper for scheduling memify from synchronous contexts."""
    try:
        return asyncio.run(schedule_profile_memify(profile_id, reason=reason, delay_s=delay_s))
    except RuntimeError:
        # Already in an event loop (unlikely in sync contexts); best-effort schedule via task.
        loop = asyncio.get_event_loop()
        loop.create_task(schedule_profile_memify(profile_id, reason=reason, delay_s=delay_s))
        return True


async def try_lock_chat_summary(profile_id: int, ttl_seconds: int) -> bool:
    key = f"ai_coach:chat_summary:profile:{profile_id}"
    try:
        client = get_redis_client()
        return bool(await client.set(key, "1", nx=True, ex=ttl_seconds))
    except Exception as exc:  # noqa: BLE001
        logger.warning("chat_summary_lock_failed profile_id={} detail={}", profile_id, exc)
        return False
