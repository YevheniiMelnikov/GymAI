import os
import shutil
import subprocess
import asyncio
from datetime import datetime, timedelta

from celery import shared_task
from loguru import logger

from bot.keyboards import workout_survey_kb
from bot.singleton import bot
from bot.texts.text_manager import msg_text
from config.env_settings import Settings
from core.cache import Cache
from core.payment_processor import PaymentProcessor
from core.services import APIService

_dumps_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dumps")
_pg_dir = os.path.join(_dumps_dir, "postgres")
_redis_dir = os.path.join(_dumps_dir, "redis")
os.makedirs(_pg_dir, exist_ok=True)
os.makedirs(_redis_dir, exist_ok=True)
os.environ["PGPASSWORD"] = Settings.DB_PASSWORD


@shared_task(bind=True, autoretry_for=(Exception,), max_retries=3)
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


@shared_task(bind=True, autoretry_for=(Exception,), max_retries=3)
def redis_backup(self):
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    src = "/app/redis/data/dump.rdb"
    dest = os.path.join(_redis_dir, f"redis_backup_{ts}.rdb")
    subprocess.run(["redis-cli", "-h", "redis", "SAVE"], check=True)
    if not os.path.exists(src):
        raise FileNotFoundError(src)
    shutil.copy(src, dest)
    logger.info(f"Redis backup saved {dest}")


@shared_task(bind=True, autoretry_for=(Exception,), max_retries=3)
def cleanup_backups(self):
    cutoff = datetime.now() - timedelta(days=30)
    for root in (_pg_dir, _redis_dir):
        for f in os.scandir(root):
            if f.is_file() and datetime.fromtimestamp(f.stat().st_ctime) < cutoff:
                os.remove(f.path)
                logger.info(f"Deleted old backup {f.path}")


@shared_task(bind=True, autoretry_for=(Exception,), max_retries=3)
def deactivate_expired_subscriptions(self):
    async def _deactivate():
        since = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        subs = await APIService.payment.get_expired_subscriptions(since)
        for sub in subs:
            if not sub.id or not sub.client_profile:
                logger.warning(f"Invalid subscription: {sub}")
                continue

            await APIService.workout.update_subscription(sub.id, dict(enabled=False, client_profile=sub.client_profile))
            Cache.workout.update_subscription(sub.client_profile, dict(enabled=False))
            Cache.workout.reset_payment_status(sub.client_profile, "subscription")
            logger.info(f"Subscription {sub.id} deactivated for user {sub.client_profile}")

    asyncio.run(_deactivate())


@shared_task(bind=True, autoretry_for=(Exception,), max_retries=3)
def process_unclosed_payments(self):
    asyncio.run(PaymentProcessor.process_unclosed_payments())


@shared_task(bind=True, autoretry_for=(Exception,), max_retries=3)
def send_daily_survey(self):
    asyncio.run(_send_daily_survey())


async def _send_daily_survey() -> None:
    clients = Cache.client.get_clients_to_survey()
    if not clients:
        logger.info("No clients to survey today")
        return

    yesterday = (datetime.now() - timedelta(days=1)).strftime("%A").lower()

    for client_id in clients:
        profile_data = await APIService.profile.get_profile(client_id)
        if not profile_data or not profile_data.get("tg_id"):
            logger.warning(f"Profile {client_id} invalid, skip")
            continue

        lang = Cache.profile.get_profile_data(profile_data["tg_id"], "language") or Settings.BOT_LANG

        try:
            await bot.send_message(
                chat_id=profile_data["tg_id"],
                text=msg_text("have_you_trained", lang),
                reply_markup=workout_survey_kb(lang, yesterday),
                disable_notification=True,
            )
            logger.info(f"Survey sent to {client_id}")
        except Exception as e:
            logger.error(f"Survey push failed for {client_id}: {e}")
