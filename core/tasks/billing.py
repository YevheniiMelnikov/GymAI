"""Billing-related Celery tasks."""

import asyncio
from datetime import datetime

from loguru import logger

from core.cache import Cache
from core.celery_app import app
from core.services import APIService

__all__ = [
    "deactivate_expired_subscriptions",
]


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=180,
    retry_jitter=True,
    max_retries=3,
)  # pyrefly: ignore[not-callable]
def deactivate_expired_subscriptions(self) -> None:
    logger.info("deactivate_expired_subscriptions started")

    async def _impl() -> None:
        today = datetime.now().date().isoformat()
        subscriptions = await APIService.payment.get_expired_subscriptions(today)

        for sub in subscriptions:
            if not sub.id or not sub.profile:
                logger.warning(f"Invalid subscription: {sub}")
                continue
            await APIService.workout.update_subscription(sub.id, {"enabled": False, "profile": sub.profile})
            await Cache.workout.update_subscription(sub.profile, {"enabled": False})
            await Cache.payment.reset_status(sub.profile, "subscription")
            logger.info(f"Subscription {sub.id} deactivated for user {sub.profile}")

    try:
        asyncio.run(_impl())
    except Exception as exc:  # noqa: BLE001
        logger.error(f"deactivate_expired_subscriptions failed: {exc}")
        raise
    logger.info("deactivate_expired_subscriptions completed")
