from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from core.cache_manager import CacheManager
from services.payment_service import PaymentService
from services.workout_service import WorkoutService


class SubscriptionManager:
    scheduler = None

    @staticmethod
    async def _run_deactivation(subscription_id, profile_id):
        try:
            await WorkoutService.update_subscription(subscription_id, {"client_profile": profile_id, "enabled": False})
            CacheManager.update_subscription_data(profile_id, {"enabled": False})
            CacheManager.reset_program_payment_status(profile_id, "subscription")
            logger.info(f"Subscription {subscription_id} for user {profile_id} deactivated")
        except Exception as e:
            logger.error(f"Failed to deactivate subscription {subscription_id} for user {profile_id}: {e}")

    @classmethod
    async def deactivate_expired_subscriptions(cls) -> None:
        now = datetime.now()
        yesterday = now - timedelta(days=1)

        try:
            expired_subscriptions = await PaymentService.get_expired_subscriptions(yesterday.strftime("%Y-%m-%d"))
            for subscription in expired_subscriptions:
                subscription_id = subscription.get("id")
                profile_id = subscription.get("user")
                if not subscription_id or not profile_id:
                    logger.warning(f"Invalid subscription format: {subscription}")
                    continue
                await cls._run_deactivation(subscription_id, profile_id)

        except Exception as e:
            logger.exception(f"Error during subscription deactivation: {e}")

    @classmethod
    async def run(cls) -> None:
        logger.debug("Starting subscription scheduler...")
        cls.scheduler = AsyncIOScheduler()
        cls.scheduler.add_job(cls.deactivate_expired_subscriptions, "cron", hour=1, minute=0)
        cls.scheduler.start()

    @classmethod
    async def shutdown(cls) -> None:
        if cls.scheduler:
            cls.scheduler.shutdown(wait=False)
