from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import loguru
from core.cache_manager import cache_manager
from services.payment_service import payment_service
from services.user_service import user_service
from services.workout_service import workout_service

logger = loguru.logger


async def deactivate_expired_subscriptions() -> None:
    now = datetime.now()
    yesterday = now - timedelta(days=1)

    try:
        expired_subscriptions = await payment_service.get_expired_subscriptions(yesterday.strftime("%Y-%m-%d"))
        for subscription in expired_subscriptions:
            if not (subscription_id := subscription.get("id")) or not (profile_id := subscription.get("user")):
                logger.warning(f"Invalid subscription format: {subscription}")
                continue

            auth_token = await user_service.get_user_token(profile_id)
            await workout_service.update_subscription(
                subscription_id, {"client_profile": profile_id, "enabled": False}, auth_token
            )
            cache_manager.update_subscription_data(profile_id, {"enabled": False})
            cache_manager.reset_program_payment_status(profile_id, "subscription")
            logger.info(f"Subscription {subscription_id} for user {profile_id} deactivated")

    except Exception as e:
        logger.exception(f"Error during subscription deactivation: {e}")


async def run() -> None:
    logger.debug("Starting subscription scheduler...")
    scheduler = AsyncIOScheduler()
    scheduler.add_job(deactivate_expired_subscriptions, "cron", hour=1, minute=0)
    scheduler.start()
