import os
import shutil
import subprocess
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
from decimal import Decimal, ROUND_HALF_UP

from celery import shared_task
import asyncio
from loguru import logger
import httpx

from config.app_settings import settings
from core.cache import Cache
from core.services import APIService
from ai_coach.cognee_coach import CogneeCoach
from bot.texts.text_manager import msg_text
from apps.payments.tasks import send_payment_message
from bot.utils.credits import required_credits
from core.services import ProfileService
from bot.utils.profiles import get_assigned_coach
from core.enums import CoachType


def _next_payment_date(period: str) -> str:
    today = date.today()
    if period == "14d":
        next_date = today + timedelta(days=14)
    elif period == "6m":
        next_date = today + relativedelta(months=+6)
    else:
        next_date = today + relativedelta(months=+1)
    return next_date.isoformat()


_dumps_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dumps")
_pg_dir = os.path.join(_dumps_dir, "postgres")
_redis_dir = os.path.join(_dumps_dir, "redis")

os.makedirs(_pg_dir, exist_ok=True)
os.makedirs(_redis_dir, exist_ok=True)
os.environ["PGPASSWORD"] = settings.DB_PASSWORD


@shared_task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyre-ignore[not-callable]
def pg_backup(self):
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    path = os.path.join(_pg_dir, f"{settings.DB_NAME}_backup_{ts}.dump")
    cmd = [
        "pg_dump",
        "-h",
        settings.DB_HOST,
        "-p",
        settings.DB_PORT,
        "-U",
        settings.DB_USER,
        "-F",
        "c",
        settings.DB_NAME,
    ]
    try:
        with open(path, "wb") as f:
            subprocess.run(cmd, stdout=f, check=True)
        logger.info(f"Postgres backup saved {path}")
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise


@shared_task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyre-ignore[not-callable]
def redis_backup(self):
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    tmp_path = f"/tmp/redis_backup_{ts}.rdb"
    final_dst = os.path.join(_redis_dir, f"redis_backup_{ts}.rdb")

    try:
        subprocess.run(["redis-cli", "-h", "redis", "--rdb", tmp_path], check=True)
        shutil.move(tmp_path, final_dst)
        logger.info(f"Redis backup saved {final_dst}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@shared_task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyre-ignore[not-callable]
def cleanup_backups(self):
    cutoff = datetime.now() - timedelta(days=settings.BACKUP_RETENTION_DAYS)
    for root in (_pg_dir, _redis_dir):
        for f in os.scandir(root):
            if f.is_file() and datetime.fromtimestamp(f.stat().st_ctime) < cutoff:
                os.remove(f.path)
                logger.info(f"Deleted old backup {f.path}")


@shared_task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyre-ignore[not-callable]
async def deactivate_expired_subscriptions(self):  # pyre-ignore[valid-type]
    today = datetime.now().date().isoformat()
    subscriptions = await APIService.payment.get_expired_subscriptions(today)

    for sub in subscriptions:
        if not sub.id or not sub.client_profile:
            logger.warning(f"Invalid subscription: {sub}")
            continue
        await APIService.workout.update_subscription(sub.id, {"enabled": False, "client_profile": sub.client_profile})
        await Cache.workout.update_subscription(sub.client_profile, {"enabled": False})
        await Cache.payment.reset_status(sub.client_profile, "subscription")
        logger.info(f"Subscription {sub.id} deactivated for user {sub.client_profile}")


@shared_task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyre-ignore[not-callable]
async def warn_low_credits(self):  # pyre-ignore[valid-type]
    tomorrow = (datetime.now() + timedelta(days=1)).date().isoformat()
    subs = await APIService.payment.get_expired_subscriptions(tomorrow)
    for sub in subs:
        if not sub.client_profile:
            continue
        client = await Cache.client.get_client(sub.client_profile)
        profile = await ProfileService.get_profile(client.profile)
        required = required_credits(Decimal(str(sub.price)))
        if client.credits < required:
            lang = profile.language if profile else settings.DEFAULT_LANG
            send_payment_message.delay(  # pyre-ignore[not-callable]
                sub.client_profile,
                msg_text("not_enough_credits", lang),
            )


@shared_task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyre-ignore[not-callable]
async def charge_due_subscriptions(self):  # pyre-ignore[valid-type]
    today = datetime.now().date().isoformat()
    subs = await APIService.payment.get_expired_subscriptions(today)
    for sub in subs:
        if not sub.id or not sub.client_profile:
            continue
        client = await Cache.client.get_client(sub.client_profile)
        required = required_credits(Decimal(str(sub.price)))
        if client.credits < required:
            await APIService.workout.update_subscription(
                sub.id, {"enabled": False, "client_profile": sub.client_profile}
            )
            await Cache.workout.update_subscription(sub.client_profile, {"enabled": False})
            await Cache.payment.reset_status(sub.client_profile, "subscription")
            continue

        await ProfileService.adjust_client_credits(client.profile, -required)
        await Cache.client.update_client(client.profile, {"credits": client.credits - required})
        if client.assigned_to:
            coach = await get_assigned_coach(client, coach_type=CoachType.human)
            if coach:
                payout = Decimal(str(sub.price)).quantize(Decimal("0.01"), ROUND_HALF_UP)
                await ProfileService.adjust_coach_payout_due(coach.profile, payout)
                new_due = (coach.payout_due or Decimal("0")) + payout
                await Cache.coach.update_coach(coach.profile, {"payout_due": str(new_due)})
        next_date = _next_payment_date(getattr(sub, "period", "1m"))
        await APIService.workout.update_subscription(sub.id, {"payment_date": next_date})
        await Cache.workout.update_subscription(sub.client_profile, {"payment_date": next_date})


@shared_task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyre-ignore[not-callable]
async def export_coach_payouts(self):  # pyre-ignore[valid-type]
    url = f"{settings.BOT_INTERNAL_URL}/internal/tasks/export_coach_payouts/"
    headers = {"Authorization": f"Api-Key {settings.API_KEY}"}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, headers=headers)
            resp.raise_for_status()
    except Exception as exc:
        logger.warning(f"Bot call failed for coach payouts: {exc}")
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    autoretry_for=(httpx.HTTPError,),
    retry_backoff=180,
    retry_jitter=True,
    max_retries=3,
)  # pyre-ignore[not-callable]
def send_daily_survey(self):
    _CONNECT_TIMEOUT = 10.0
    _READ_TIMEOUT = 30.0

    url = f"{settings.BOT_INTERNAL_URL}/internal/tasks/send_daily_survey/"
    headers = {"Authorization": f"Api-Key {settings.API_KEY}"}

    try:
        timeout = httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT)
        resp = httpx.post(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(f"Bot call failed for daily survey: {exc!s}")
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    autoretry_for=(httpx.HTTPError,),
    retry_backoff=180,
    retry_jitter=True,
    max_retries=3,
)  # pyre-ignore[not-callable]
def send_workout_result(self, coach_profile_id: int, client_profile_id: int, text: str) -> None:
    """Forward workout survey results to the appropriate recipient."""

    url = f"{settings.BOT_INTERNAL_URL}/internal/tasks/send_workout_result/"
    headers = {"Authorization": f"Api-Key {settings.API_KEY}"}
    payload = {
        "coach_id": coach_profile_id,
        "client_id": client_profile_id,
        "text": text,
    }

    try:
        resp = httpx.post(url, json=payload, timeout=15.0, headers=headers)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(f"Bot call failed for workout result: {exc!s}")
        raise self.retry(exc=exc)


@shared_task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyre-ignore[not-callable]
def refresh_external_knowledge(self):
    """Refresh external knowledge and rebuild Cognee index."""
    logger.info("refresh_external_knowledge triggered")
    try:
        asyncio.run(CogneeCoach.refresh_knowledge_base())
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Knowledge refresh failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyre-ignore[not-callable]
async def prune_cognee(self):  # pyre-ignore[valid-type]
    """Remove cached Cognee data storage."""
    url = f"{settings.BOT_INTERNAL_URL}/internal/tasks/prune_cognee/"
    headers = {"Authorization": f"Api-Key {settings.API_KEY}"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers)
            resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Bot call failed for prune_cognee: {exc}")
        raise self.retry(exc=exc)
