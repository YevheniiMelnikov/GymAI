import asyncio
import functools
import os
import subprocess
from datetime import datetime, timedelta

import loguru
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = loguru.logger

DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(CURRENT_DIR, "dumps")
POSTGRES_BACKUP_DIR = os.path.join(BACKUP_DIR, "postgres")
REDIS_BACKUP_DIR = os.path.join(BACKUP_DIR, "redis")
os.environ["PGPASSWORD"] = DB_PASSWORD

for directory in [POSTGRES_BACKUP_DIR, REDIS_BACKUP_DIR]:
    os.makedirs(directory, exist_ok=True)


async def run_subprocess(command, **kwargs):
    loop = asyncio.get_event_loop()
    func = functools.partial(subprocess.run, command, **kwargs)
    return await loop.run_in_executor(None, func)


async def create_postgres_backup() -> None:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"{DB_NAME}_backup_{timestamp}.dump"
    filepath = os.path.join(POSTGRES_BACKUP_DIR, filename)
    command = ["pg_dump", "-h", DB_HOST, "-p", DB_PORT, "-U", DB_USER, "-F", "c", DB_NAME]

    try:
        with open(filepath, "wb") as f:
            result = await run_subprocess(command, stdout=f, stderr=subprocess.PIPE)

        if result.returncode == 0:
            logger.info(f"PostgreSQL backup {filename} сохранён по пути {filepath}")
        else:
            logger.error(f"PostgreSQL backup {filename} не удался: {result.stderr.decode().strip()}")
            if os.path.exists(filepath):
                os.remove(filepath)
    except Exception as e:
        logger.error(f"Exception during PostgreSQL backup: {e}")
        if os.path.exists(filepath):
            os.remove(filepath)


async def create_redis_backup() -> None:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_filename = f"redis_backup_{timestamp}.rdb"
    backup_filepath = os.path.join(REDIS_BACKUP_DIR, backup_filename)

    try:
        save_command = ["redis-cli", "-h", "redis", "SAVE"]
        result_save = await run_subprocess(save_command, capture_output=True, text=True)
        if result_save.returncode != 0:
            logger.error(f"Redis SAVE command failed: {result_save.stderr}")
            return

        source_dump = "/opt/redis/data/dump.rdb"

        if not os.path.exists(source_dump):
            logger.error(f"Source dump.rdb not found at {source_dump}")
            return

        with open(source_dump, "rb") as src, open(backup_filepath, "wb") as dest:
            dest.write(src.read())

        logger.info(f"Redis backup сохранён по пути {backup_filepath}")

    except Exception as e:
        logger.error(f"Exception during Redis backup: {e}")


async def delete_old_backups() -> None:
    now = datetime.now()
    retention_period = timedelta(days=30)

    for backup_dir, db_type in [(POSTGRES_BACKUP_DIR, "PostgreSQL"), (REDIS_BACKUP_DIR, "Redis")]:
        for filename in os.listdir(backup_dir):
            if db_type == "PostgreSQL" and filename.startswith(DB_NAME) and filename.endswith(".dump"):
                filepath = os.path.join(backup_dir, filename)
            elif db_type == "Redis" and filename.startswith("redis_backup_") and filename.endswith(".rdb"):
                filepath = os.path.join(backup_dir, filename)
            else:
                continue

            file_creation_time = datetime.fromtimestamp(os.path.getctime(filepath))
            if now - file_creation_time > retention_period:
                try:
                    os.remove(filepath)
                    logger.info(f"Deleted old {db_type} backup: {filename}")
                except Exception as e:
                    logger.error(f"Failed to delete {db_type} backup {filename}: {e}")


async def backup_scheduler() -> None:
    logger.debug("Starting backup scheduler ...")
    scheduler = AsyncIOScheduler()
    scheduler.add_job(create_postgres_backup, "cron", hour=15, minute=25)
    scheduler.add_job(create_redis_backup, "cron", hour=15, minute=25)
    scheduler.add_job(delete_old_backups, "cron", hour=13, minute=42)
    scheduler.start()
