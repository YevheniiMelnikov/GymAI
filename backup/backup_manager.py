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
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(CURRENT_DIR, "dumps")
os.environ["PGPASSWORD"] = DB_PASSWORD
if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)


async def create_backup() -> None:
    filename = f"{DB_NAME}_backup_{datetime.now().strftime('%Y%m%d%H%M%S')}.sql"
    filepath = os.path.join(BACKUP_DIR, filename)
    command = f"pg_dump -h {DB_HOST} -U {DB_USER} -F c {DB_NAME} > {filepath}"
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        logger.info(f"Backup {filename} saved to {filepath}")
    else:
        logger.error(f"Backup {filename} failed: {result.stderr}")


async def delete_old_backups() -> None:
    now = datetime.now()
    for filename in os.listdir(BACKUP_DIR):
        if filename.startswith(DB_NAME) and filename.endswith(".sql"):
            filepath = os.path.join(BACKUP_DIR, filename)
            file_creation_time = datetime.fromtimestamp(os.path.getctime(filepath))
            if now - file_creation_time > timedelta(days=30):
                os.remove(filepath)
                logger.info(f"Deleted old backup: {filename}")


async def backup_scheduler() -> None:
    logger.debug("Starting backup scheduler ...")
    scheduler = AsyncIOScheduler()
    scheduler.add_job(create_backup, "cron", hour=2, minute=0)
    scheduler.add_job(delete_old_backups, "cron", hour=2, minute=10)
    scheduler.start()
