from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from common.logger import logger
from core.cache_manager import CacheManager
from services.payment_service import PaymentService
from services.user_service import user_service
from services.workout_service import workout_service


class SubscriptionManager:
    def __init__(self):
        self.scheduler = None

    @staticmethod
    async def _run_deactivation(subscription_id, profile_id):
        try:
            auth_token = await user_service.get_user_token(profile_id)
            await workout_service.update_subscription(
                subscription_id, {"client_profile": profile_id, "enabled": False}, auth_token
            )
            CacheManager.update_subscription_data(profile_id, {"enabled": False})
            CacheManager.reset_program_payment_status(profile_id, "subscription")
            logger.info(f"Subscription {subscription_id} for user {profile_id} deactivated")
        except Exception as e:
            logger.error(f"Failed to deactivate subscription {subscription_id} for user {profile_id}: {e}")

    async def deactivate_expired_subscriptions(self) -> None:
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
                await self._run_deactivation(subscription_id, profile_id)

        except Exception as e:
            logger.exception(f"Error during subscription deactivation: {e}")

    async def run(self) -> None:
        logger.debug("Starting subscription scheduler...")
        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_job(self.deactivate_expired_subscriptions, "cron", hour=1, minute=0)
        self.scheduler.start()

    async def shutdown(self) -> None:
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            logger.debug("Subscription scheduler stopped")


subscription_manager = SubscriptionManager()


async def run() -> None:
    await subscription_manager.run()


async def shutdown() -> None:
    if subscription_manager.scheduler:
        await subscription_manager.shutdown()
