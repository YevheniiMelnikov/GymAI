import asyncio
import functools
import os
import subprocess
import shutil
from datetime import datetime, timedelta

import loguru
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from common.settings import settings

logger = loguru.logger


class BackupManager:
    def __init__(self):
        self.scheduler = None
        os.environ["PGPASSWORD"] = settings.DB_PASSWORD
        self.current_dir = os.path.dirname(os.path.abspath(__file__))
        self.backup_dir = os.path.join(os.path.dirname(self.current_dir), "dumps")
        self.postgres_backup_dir = os.path.join(self.backup_dir, "postgres")
        self.redis_backup_dir = os.path.join(self.backup_dir, "redis")

        for directory in [self.postgres_backup_dir, self.redis_backup_dir]:
            os.makedirs(directory, exist_ok=True)

    @staticmethod
    async def _run_subprocess(command, **kwargs):
        loop = asyncio.get_event_loop()
        func = functools.partial(subprocess.run, command, **kwargs)
        return await loop.run_in_executor(None, func)

    async def create_postgres_backup(self) -> None:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"{settings.DB_NAME}_backup_{timestamp}.dump"
        filepath = os.path.join(self.postgres_backup_dir, filename)
        command = [
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
            with open(filepath, "wb") as f:
                result = await self._run_subprocess(command, stdout=f, stderr=subprocess.PIPE)
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

    async def create_redis_backup(self) -> None:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_filename = f"redis_backup_{timestamp}.rdb"
        backup_filepath = os.path.join(self.redis_backup_dir, backup_filename)

        try:
            save_command = ["redis-cli", "-h", "redis", "SAVE"]
            result_save = await self._run_subprocess(save_command, capture_output=True, text=True)
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

    async def cleanup_backups(self) -> None:
        now = datetime.now()
        retention_period = timedelta(days=30)

        for filename in os.listdir(self.postgres_backup_dir):
            if filename.startswith(settings.DB_NAME) and filename.endswith(".dump"):
                filepath = os.path.join(self.postgres_backup_dir, filename)
                file_creation_time = datetime.fromtimestamp(os.path.getctime(filepath))
                if now - file_creation_time > retention_period:
                    try:
                        os.remove(filepath)
                        logger.info(f"Deleted old PostgreSQL backup: {filename}")
                    except Exception as e:
                        logger.error(f"Failed to delete PostgreSQL backup {filename}: {e}")

        for filename in os.listdir(self.redis_backup_dir):
            if filename.startswith("redis_backup_") and filename.endswith(".rdb"):
                filepath = os.path.join(self.redis_backup_dir, filename)
                file_creation_time = datetime.fromtimestamp(os.path.getctime(filepath))
                if now - file_creation_time > retention_period:
                    try:
                        os.remove(filepath)
                        logger.info(f"Deleted old Redis backup: {filename}")
                    except Exception as e:
                        logger.error(f"Failed to delete Redis backup {filename}: {e}")

    async def run(self) -> None:
        logger.debug("Starting backup scheduler...")
        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_job(self.create_postgres_backup, "cron", hour=2, minute=0)
        self.scheduler.add_job(self.create_redis_backup, "cron", hour=2, minute=1)
        self.scheduler.add_job(self.cleanup_backups, "cron", hour=2, minute=2)
        self.scheduler.start()

    async def shutdown(self) -> None:
        self.scheduler.shutdown(wait=False)
        logger.debug("Backup scheduler stopped")


backup_manager = BackupManager()


async def run() -> None:
    await backup_manager.run()


async def shutdown() -> None:
    if backup_manager.scheduler:
        await backup_manager.shutdown()
