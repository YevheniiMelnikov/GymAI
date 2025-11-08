"""Billing-related Celery tasks."""

import asyncio
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import cast

from dateutil.relativedelta import relativedelta
from loguru import logger

from apps.payments.tasks import send_payment_message
from bot.texts.text_manager import msg_text
from bot.utils.profiles import get_assigned_coach
from config.app_settings import settings
from core.cache import Cache
from core.celery_app import app
from core.enums import CoachType, SubscriptionPeriod
from core.services import APIService

__all__ = [
    "deactivate_expired_subscriptions",
    "warn_low_credits",
    "charge_due_subscriptions",
]


def _next_payment_date(period: SubscriptionPeriod = SubscriptionPeriod.one_month) -> str:
    today = date.today()
    if period is SubscriptionPeriod.six_months:
        next_date = cast(date, today + relativedelta(months=+6))  # pyrefly: ignore[redundant-cast]
    else:
        next_date = cast(date, today + relativedelta(months=+1))  # pyrefly: ignore[redundant-cast]
    return next_date.isoformat()


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
            if not sub.id or not sub.client_profile:
                logger.warning(f"Invalid subscription: {sub}")
                continue
            await APIService.workout.update_subscription(
                sub.id, {"enabled": False, "client_profile": sub.client_profile}
            )
            await Cache.workout.update_subscription(sub.client_profile, {"enabled": False})
            await Cache.payment.reset_status(sub.client_profile, "subscription")
            logger.info(f"Subscription {sub.id} deactivated for user {sub.client_profile}")

    try:
        asyncio.run(_impl())
    except Exception as exc:  # noqa: BLE001
        logger.error(f"deactivate_expired_subscriptions failed: {exc}")
        raise
    logger.info("deactivate_expired_subscriptions completed")


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=180,
    retry_jitter=True,
    max_retries=3,
)  # pyrefly: ignore[not-callable]
def warn_low_credits(self) -> None:
    logger.info("warn_low_credits started")

    async def _impl() -> None:
        tomorrow = (datetime.now() + timedelta(days=1)).date().isoformat()
        subs = await APIService.payment.get_expired_subscriptions(tomorrow)
        for sub in subs:
            if not sub.client_profile:
                continue
            client = await Cache.client.get_client(sub.client_profile)
            profile = await APIService.profile.get_profile(client.profile)
            required = int(sub.price)
            if client.credits < required:
                lang = profile.language if profile else settings.DEFAULT_LANG
                send_payment_message.delay(  # pyrefly: ignore[not-callable]
                    sub.client_profile,
                    msg_text("not_enough_credits", lang),
                )

    try:
        asyncio.run(_impl())
    except Exception as exc:  # noqa: BLE001
        logger.error(f"warn_low_credits failed: {exc}")
        raise
    logger.info("warn_low_credits completed")


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=180,
    retry_jitter=True,
    max_retries=3,
)  # pyrefly: ignore[not-callable]
def charge_due_subscriptions(self) -> None:
    logger.info("charge_due_subscriptions started")

    async def _impl() -> None:
        today = datetime.now().date().isoformat()
        subs = await APIService.payment.get_expired_subscriptions(today)
        for sub in subs:
            if not sub.id or not sub.client_profile:
                continue
            client = await Cache.client.get_client(sub.client_profile)
            required = int(sub.price)
            if client.credits < required:
                await APIService.workout.update_subscription(
                    sub.id, {"enabled": False, "client_profile": sub.client_profile}
                )
                await Cache.workout.update_subscription(sub.client_profile, {"enabled": False})
                await Cache.payment.reset_status(sub.client_profile, "subscription")
                continue

            await APIService.profile.adjust_client_credits(client.profile, -required)
            await Cache.client.update_client(client.profile, {"credits": client.credits - required})
            if client.assigned_to:
                coach = await get_assigned_coach(client, coach_type=CoachType.human)
                if coach:
                    payout = (Decimal(sub.price) * settings.CREDIT_RATE_MAX_PACK).quantize(
                        Decimal("0.01"), ROUND_HALF_UP
                    )
                    await APIService.profile.adjust_coach_payout_due(coach.profile, payout)
                    new_due = (coach.payout_due or Decimal("0")) + payout
                    await Cache.coach.update_coach(coach.profile, {"payout_due": str(new_due)})
            period_str = getattr(sub, "period", SubscriptionPeriod.one_month.value)
            period = SubscriptionPeriod(period_str)
            next_date = _next_payment_date(period)
            await APIService.workout.update_subscription(sub.id, {"payment_date": next_date})
            await Cache.workout.update_subscription(sub.client_profile, {"payment_date": next_date})

    try:
        asyncio.run(_impl())
    except Exception as exc:  # noqa: BLE001
        logger.error(f"charge_due_subscriptions failed: {exc}")
        raise
    logger.info("charge_due_subscriptions completed")
