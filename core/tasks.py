import os
import shutil
import subprocess
import asyncio
from datetime import datetime, timedelta

from celery import shared_task
from loguru import logger
from config.env_settings import Settings
from core.cache_manager import CacheManager
from services.payment_service import PaymentService
from services.workout_service import WorkoutService

_dumps_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dumps")
_pg_dir = os.path.join(_dumps_dir, "postgres")
_redis_dir = os.path.join(_dumps_dir, "redis")
os.makedirs(_pg_dir, exist_ok=True)
os.makedirs(_redis_dir, exist_ok=True)
os.environ["PGPASSWORD"] = Settings.DB_PASSWORD


@shared_task(name="project.tasks.pg_backup", bind=True, autoretry_for=(Exception,), max_retries=3)
def pg_backup(self):
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    path = os.path.join(_pg_dir, f"{Settings.DB_NAME}_backup_{ts}.dump")
    cmd = [
        "pg_dump",
        "-h",
        Settings.DB_HOST,
        "-p",
        Settings.DB_PORT,
        "-U",
        Settings.DB_USER,
        "-F",
        "c",
        Settings.DB_NAME,
    ]
    try:
        with open(path, "wb") as f:
            subprocess.run(cmd, stdout=f, check=True)
        logger.info(f"Postgres backup saved {path}")
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise


@shared_task(name="project.tasks.redis_backup", bind=True, autoretry_for=(Exception,), max_retries=3)
def redis_backup(self):
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    src = "/app/redis/data/dump.rdb"
    dest = os.path.join(_redis_dir, f"redis_backup_{ts}.rdb")
    subprocess.run(["redis-cli", "-h", "redis", "SAVE"], check=True)
    if not os.path.exists(src):
        raise FileNotFoundError(src)
    shutil.copy(src, dest)
    logger.info(f"Redis backup saved {dest}")


@shared_task(name="project.tasks.cleanup_backups", bind=True, autoretry_for=(Exception,), max_retries=3)
def cleanup_backups(self):
    cutoff = datetime.now() - timedelta(days=30)
    for root in (_pg_dir, _redis_dir):
        for f in os.scandir(root):
            if f.is_file() and datetime.fromtimestamp(f.stat().st_ctime) < cutoff:
                os.remove(f.path)
                logger.info(f"Deleted old backup {f.path}")


@shared_task(
    name="project.tasks.deactivate_expired_subscriptions", bind=True, autoretry_for=(Exception,), max_retries=3
)
def deactivate_expired_subscriptions(self):
    async def _deactivate():
        since = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        subs = await PaymentService.get_expired_subscriptions(since)
        for sub in subs:
            s_id, p_id = sub.get("id"), sub.get("user")
            if not s_id or not p_id:
                logger.warning(f"Invalid subscription: {sub}")
                continue
            await WorkoutService.update_subscription(s_id, dict(enabled=False, client_profile=p_id))
            CacheManager.update_subscription_data(p_id, dict(enabled=False))
            CacheManager.reset_program_payment_status(p_id, "subscription")
            logger.info(f"Subscription {s_id} deactivated for user {p_id}")

    asyncio.run(_deactivate())
