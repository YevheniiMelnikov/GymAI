"""Database and cache backup tasks."""

import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

from config.app_settings import settings
from core.celery_app import app

__all__ = [
    "pg_backup",
    "redis_backup",
    "cleanup_backups",
]

_BASE_DIR: Path = Path(__file__).resolve().parents[2]
_DUMPS_DIR: Path = _BASE_DIR / "dumps"
_PG_DIR: Path = _DUMPS_DIR / "postgres"
_REDIS_DIR: Path = _DUMPS_DIR / "redis"

_PG_DIR.mkdir(parents=True, exist_ok=True)
_REDIS_DIR.mkdir(parents=True, exist_ok=True)


@app.task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyrefly: ignore[not-callable]
def pg_backup(self) -> None:
    ts: str = datetime.now().strftime("%Y%m%d%H%M%S")
    path: Path = _PG_DIR / f"{settings.DB_NAME}_backup_{ts}.dump"
    cmd: list[str] = [
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
        with path.open("wb") as handle:
            subprocess.run(cmd, stdout=handle, check=True)
        logger.info(f"Postgres backup saved {path}")
    except Exception:
        if path.exists():
            path.unlink()
        raise


@app.task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyrefly: ignore[not-callable]
def redis_backup(self) -> None:
    ts: str = datetime.now().strftime("%Y%m%d%H%M%S")
    tmp_path: Path = Path("/tmp") / f"redis_backup_{ts}.rdb"
    final_dst: Path = _REDIS_DIR / f"redis_backup_{ts}.rdb"

    try:
        subprocess.run(
            ["redis-cli", "-u", settings.REDIS_URL, "--rdb", str(tmp_path)],
            check=True,
        )
        shutil.move(str(tmp_path), str(final_dst))
        logger.info(f"Redis backup saved {final_dst}")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@app.task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyrefly: ignore[not-callable]
def cleanup_backups(self) -> None:
    cutoff: datetime = datetime.now() - timedelta(days=settings.BACKUP_RETENTION_DAYS)
    roots: tuple[Path, Path] = (_PG_DIR, _REDIS_DIR)
    for root_dir in roots:
        entries: list[Path] = list(root_dir.iterdir())
        for candidate_path in entries:
            if candidate_path.is_file() and datetime.fromtimestamp(candidate_path.stat().st_ctime) < cutoff:
                candidate_path.unlink()
                logger.info(f"Deleted old backup {candidate_path}")
