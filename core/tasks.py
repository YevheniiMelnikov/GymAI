import os
import shutil
import subprocess
from datetime import datetime, timedelta

from celery import shared_task
from loguru import logger
import httpx

from config.env_settings import settings
from core.cache import Cache
from core.services import APIService

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
    cutoff = datetime.now() - timedelta(days=30)
    for root in (_pg_dir, _redis_dir):
        for f in os.scandir(root):
            if f.is_file() and datetime.fromtimestamp(f.stat().st_ctime) < cutoff:
                os.remove(f.path)
                logger.info(f"Deleted old backup {f.path}")


@shared_task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyre-ignore[not-callable]
async def deactivate_expired_subscriptions(self):  # pyre-ignore[valid-type]
    since = (datetime.now() - timedelta(days=1)).date().isoformat()
    subscriptions = await APIService.payment.get_expired_subscriptions(since)

    for sub in subscriptions:
        if not sub.id or not sub.client_profile:
            logger.warning(f"Invalid subscription: {sub}")
            continue
        await APIService.workout.update_subscription(sub.id, {"enabled": False, "client_profile": sub.client_profile})
        await Cache.workout.update_subscription(sub.client_profile, {"enabled": False})
        await Cache.payment.reset_status(sub.client_profile, "subscription")
        logger.info(f"Subscription {sub.id} deactivated for user {sub.client_profile}")


@shared_task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyre-ignore[not-callable]
def process_unclosed_payments(self):
    async def _call_bot() -> None:
        url = f"{settings.BOT_INTERNAL_URL}/internal/tasks/process_unclosed_payments/"
        headers = {"Authorization": f"Api-Key {settings.API_KEY}"}
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, headers=headers)
            resp.raise_for_status()

    import asyncio

    try:
        asyncio.run(_call_bot())
    except Exception as exc:
        logger.warning(f"Bot call failed for unclosed payments: {exc}")
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
