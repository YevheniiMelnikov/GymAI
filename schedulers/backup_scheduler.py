import asyncio
import functools
import os
import subprocess
import shutil
from datetime import datetime, timedelta

from common.logger import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from common.settings import Settings


class BackupManager:
    scheduler = None
    os.environ["PGPASSWORD"] = Settings.DB_PASSWORD
    current_dir = os.path.dirname(os.path.abspath(__file__))
    backup_dir = os.path.join(os.path.dirname(current_dir), "dumps")
    postgres_backup_dir = os.path.join(backup_dir, "postgres")
    redis_backup_dir = os.path.join(backup_dir, "redis")

    @staticmethod
    async def _run_subprocess(command, **kwargs):
        loop = asyncio.get_event_loop()
        func = functools.partial(subprocess.run, command, **kwargs)
        return await loop.run_in_executor(None, func)

    @classmethod
    async def create_postgres_backup(cls) -> None:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"{Settings.DB_NAME}_backup_{timestamp}.dump"
        filepath = os.path.join(cls.postgres_backup_dir, filename)
        command = [
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
            with open(filepath, "wb") as f:
                result = await cls._run_subprocess(command, stdout=f, stderr=subprocess.PIPE)
            if result.returncode == 0:
                logger.info(f"PostgreSQL backup {filename} saved successfully at {filepath}")
            else:
                logger.error(f"PostgreSQL backup {filename} failed: {result.stderr.decode().strip()}")
                if os.path.exists(filepath):
                    os.remove(filepath)
        except Exception as e:
            logger.error(f"Exception during PostgreSQL backup: {e}")
            if os.path.exists(filepath):
                os.remove(filepath)

    @classmethod
    async def create_redis_backup(cls) -> None:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_filename = f"redis_backup_{timestamp}.rdb"
        backup_filepath = os.path.join(cls.redis_backup_dir, backup_filename)

        try:
            save_command = ["redis-cli", "-h", "redis", "SAVE"]
            result_save = await cls._run_subprocess(save_command, capture_output=True, text=True)
            if result_save.returncode != 0:
                logger.error(f"Redis SAVE command failed: {result_save.stderr}")
                return

            source_dump = "/opt/redis/data/dump.rdb"
            if not os.path.exists(source_dump):
                logger.error(f"Source dump.rdb not found at {source_dump}")
                return

            shutil.copy(source_dump, backup_filepath)
            logger.info(f"Redis backup saved successfully at {backup_filepath}")

        except Exception as e:
            logger.error(f"Exception during Redis backup: {e}")

    @classmethod
    async def cleanup_backups(cls) -> None:
        now = datetime.now()
        retention_period = timedelta(days=30)

        for filename in os.listdir(cls.postgres_backup_dir):
            if filename.startswith(Settings.DB_NAME) and filename.endswith(".dump"):
                filepath = os.path.join(cls.postgres_backup_dir, filename)
                file_creation_time = datetime.fromtimestamp(os.path.getctime(filepath))
                if now - file_creation_time > retention_period:
                    try:
                        os.remove(filepath)
                        logger.info(f"Deleted old PostgreSQL backup: {filename}")
                    except Exception as e:
                        logger.error(f"Failed to delete PostgreSQL backup {filename}: {e}")

        for filename in os.listdir(cls.redis_backup_dir):
            if filename.startswith("redis_backup_") and filename.endswith(".rdb"):
                filepath = os.path.join(cls.redis_backup_dir, filename)
                file_creation_time = datetime.fromtimestamp(os.path.getctime(filepath))
                if now - file_creation_time > retention_period:
                    try:
                        os.remove(filepath)
                        logger.info(f"Deleted old Redis backup: {filename}")
                    except Exception as e:
                        logger.error(f"Failed to delete Redis backup {filename}: {e}")

    @classmethod
    async def run(cls) -> None:
        for directory in [cls.postgres_backup_dir, cls.redis_backup_dir]:
            os.makedirs(directory, exist_ok=True)

        logger.debug("Starting backup scheduler...")
        cls.scheduler = AsyncIOScheduler()
        cls.scheduler.add_job(cls.create_postgres_backup, "cron", hour=2, minute=0)
        cls.scheduler.add_job(cls.create_redis_backup, "cron", hour=2, minute=1)
        cls.scheduler.add_job(cls.cleanup_backups, "cron", hour=2, minute=2)
        cls.scheduler.start()

    @classmethod
    async def shutdown(cls) -> None:
        cls.scheduler.shutdown(wait=False)
