"""Database and cache backup tasks."""

import os
import shutil
import subprocess
from datetime import datetime, timedelta

from loguru import logger

from config.app_settings import settings
from core.celery_app import app

__all__ = [
    "pg_backup",
    "redis_backup",
    "cleanup_backups",
]

_dumps_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dumps")
_pg_dir = os.path.join(_dumps_dir, "postgres")
_redis_dir = os.path.join(_dumps_dir, "redis")

os.makedirs(_pg_dir, exist_ok=True)
os.makedirs(_redis_dir, exist_ok=True)


@app.task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyrefly: ignore[not-callable]
def pg_backup(self) -> None:
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


@app.task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyrefly: ignore[not-callable]
def redis_backup(self) -> None:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    tmp_path = f"/tmp/redis_backup_{ts}.rdb"
    final_dst = os.path.join(_redis_dir, f"redis_backup_{ts}.rdb")

    try:
        subprocess.run(
            ["redis-cli", "-u", settings.REDIS_URL, "--rdb", tmp_path],
            check=True,
        )
        shutil.move(tmp_path, final_dst)
        logger.info(f"Redis backup saved {final_dst}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyrefly: ignore[not-callable]
def cleanup_backups(self) -> None:
    cutoff = datetime.now() - timedelta(days=settings.BACKUP_RETENTION_DAYS)
    for root in (_pg_dir, _redis_dir):
        for f in os.scandir(root):
            if f.is_file() and datetime.fromtimestamp(f.stat().st_ctime) < cutoff:
                os.remove(f.path)
                logger.info(f"Deleted old backup {f.path}")
