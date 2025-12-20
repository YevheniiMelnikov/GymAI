import asyncio

from loguru import logger

from config.app_settings import settings
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
    delay_value = float(delay_s if delay_s is not None else settings.AI_COACH_MEMIFY_DELAY_SECONDS)
    countdown = max(delay_value, 0.0)
    dedupe_ttl = int(countdown) + 300
    key = f"ai_coach:memify:profile:{profile_id}"
    datasets = _dataset_labels(profile_id)
    try:
        client = get_redis_client()
        already_scheduled = not await client.set(key, "1", nx=True, ex=dedupe_ttl)
    except Exception as exc:  # noqa: BLE001
        logger.warning("memify_schedule_dedupe_failed profile_id={} detail={}", profile_id, exc)
        return False
    if already_scheduled:
        logger.info(
            "memify_schedule_skipped profile_id={} datasets={} reason=dedupe_hit delay_s={}",
            profile_id,
            datasets,
            countdown,
        )
        return False

    try:
        from core.tasks.ai_coach.maintenance import memify_profile_datasets

        task = memify_profile_datasets.apply_async(
            kwargs={"profile_id": profile_id, "reason": reason},
            countdown=countdown,
        )
        logger.info(
            "memify_schedule_enqueued profile_id={} datasets={} reason={} delay_s={} task_id={}",
            profile_id,
            datasets,
            reason,
            countdown,
            getattr(task, "id", "unknown"),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("memify_schedule_failed profile_id={} detail={}", profile_id, exc)
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
