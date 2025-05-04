import shutil
import os
import subprocess
from datetime import datetime, timedelta
from celery import Celery, shared_task
from config.env_settings import Settings
from services.payment_service import PaymentService
from services.workout_service import WorkoutService
from core.cache_manager import CacheManager

celery_app = Celery("project")
celery_app.config_from_object("config.celery")


@shared_task
def pg_backup():
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    fname = f"{Settings.DB_NAME}_backup_{ts}.dump"
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
    with open(f"/dumps/postgres/{fname}", "wb") as f:
        subprocess.run(cmd, stdout=f, check=True)


@shared_task
def redis_backup():
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    subprocess.run(["redis-cli", "-h", "redis", "SAVE"], check=True)
    shutil.copy("/app/redis/data/dump.rdb", f"/dumps/redis/redis_backup_{ts}.rdb")


@shared_task
def cleanup_backups():
    now = datetime.now() - timedelta(days=30)
    for folder in ("postgres", "redis"):
        for f in os.scandir(f"/dumps/{folder}"):
            if f.stat().st_ctime < now.timestamp():
                os.remove(f.path)


@shared_task
def deactivate_subscriptions():
    yest = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    for sub in PaymentService.get_expired_subscriptions_sync(yest):
        sid, pid = sub["id"], sub["user"]
        WorkoutService.update_subscription_sync(sid, {"client_profile": pid, "enabled": False})
        CacheManager.update_subscription_data(pid, {"enabled": False})
        CacheManager.reset_program_payment_status(pid, "subscription")
