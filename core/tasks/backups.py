"""Database and cache backup tasks."""

import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from loguru import logger

from config.app_settings import settings
from core.celery_app import app

__all__ = [
    "pg_backup",
    "redis_backup",
    "neo4j_backup",
    "qdrant_backup",
    "cleanup_backups",
]

_BASE_DIR: Path = Path(__file__).resolve().parents[2]
_DUMPS_DIR: Path = _BASE_DIR / "dumps"
_PG_DIR: Path = _DUMPS_DIR / "postgres"
_REDIS_DIR: Path = _DUMPS_DIR / "redis"
_NEO4J_DIR: Path = _DUMPS_DIR / "neo4j"
_QDRANT_DIR: Path = _DUMPS_DIR / "qdrant"

_PG_DIR.mkdir(parents=True, exist_ok=True)
_REDIS_DIR.mkdir(parents=True, exist_ok=True)
_NEO4J_DIR.mkdir(parents=True, exist_ok=True)
_QDRANT_DIR.mkdir(parents=True, exist_ok=True)


def _kb_backups_enabled() -> bool:
    return bool(getattr(settings, "ENABLE_KB_BACKUPS", False))


def _sanitize_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("._") or "unknown"


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
def neo4j_backup(self) -> None:
    if not _kb_backups_enabled():
        logger.info("Neo4j backup skipped: disabled")
        return
    ts: str = datetime.now().strftime("%Y%m%d%H%M%S")
    path: Path = _NEO4J_DIR / f"neo4j_backup_{ts}.json"
    host = (settings.GRAPH_DATABASE_HOST or "neo4j").strip() or "neo4j"
    port = str(settings.GRAPH_DATABASE_PORT or "7687")
    username = settings.GRAPH_DATABASE_USERNAME
    password = settings.GRAPH_DATABASE_PASSWORD
    database = settings.GRAPH_DATABASE_NAME or "neo4j"
    if not username or not password:
        raise RuntimeError("Neo4j credentials are not configured")
    try:
        from neo4j import GraphDatabase
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Neo4j backup skipped: missing driver ({exc})")
        return
    driver = GraphDatabase.driver(f"bolt://{host}:{port}", auth=(username, password))
    try:
        with driver.session(database=database) as session:
            result = session.run("CALL apoc.export.json.all(null, {stream: true, useTypes: true})")
            wrote_any = False
            with path.open("w", encoding="utf-8") as handle:
                for record in result:
                    payload = record.get("data") or ""
                    if not payload:
                        continue
                    handle.write(str(payload))
                    wrote_any = True
            if not wrote_any:
                raise RuntimeError("Neo4j export payload is empty")
        logger.info(f"Neo4j backup saved {path}")
    finally:
        driver.close()


@app.task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyrefly: ignore[not-callable]
def qdrant_backup(self) -> None:
    if not _kb_backups_enabled():
        logger.info("Qdrant backup skipped: disabled")
        return
    ts: str = datetime.now().strftime("%Y%m%d%H%M%S")
    base_url = settings.VECTOR_DB_URL.rstrip("/")
    headers: dict[str, str] = {}
    if settings.VECTOR_DB_KEY:
        headers["api-key"] = settings.VECTOR_DB_KEY
    with httpx.Client(timeout=60) as client:
        resp = client.get(f"{base_url}/collections", headers=headers)
        resp.raise_for_status()
        payload = resp.json()
        collections = payload.get("result", {}).get("collections", [])
        if not collections:
            logger.info("Qdrant backup skipped: no collections")
            return
        for item in collections:
            name = item.get("name") if isinstance(item, dict) else None
            if not name:
                continue
            snap_resp = client.post(f"{base_url}/collections/{name}/snapshots", headers=headers)
            snap_resp.raise_for_status()
            snap_name = snap_resp.json().get("result", {}).get("name")
            if not snap_name:
                raise RuntimeError(f"Qdrant snapshot name missing for collection {name}")
            safe_name = _sanitize_component(str(name))
            safe_snap = _sanitize_component(str(snap_name))
            target = _QDRANT_DIR / f"qdrant_{safe_name}_{safe_snap}_{ts}.snapshot"
            tmp_target = target.with_suffix(f"{target.suffix}.tmp")
            download_url = f"{base_url}/collections/{name}/snapshots/{snap_name}"
            retries = [0.5, 1.0, 2.0, 4.0, 8.0]
            last_error: Exception | None = None
            for wait_s in retries:
                with client.stream("GET", download_url, headers=headers) as response:
                    if response.status_code in {404, 409, 423, 425, 503}:
                        last_error = httpx.HTTPStatusError(
                            f"Snapshot not ready: {response.status_code}",
                            request=response.request,
                            response=response,
                        )
                    else:
                        response.raise_for_status()
                        with tmp_target.open("wb") as handle:
                            for chunk in response.iter_bytes():
                                if chunk:
                                    handle.write(chunk)
                        tmp_target.replace(target)
                        logger.info(f"Qdrant snapshot saved {target}")
                        last_error = None
                        break
                time.sleep(wait_s)
            if last_error is not None:
                if tmp_target.exists():
                    tmp_target.unlink()
                raise last_error


@app.task(bind=True, autoretry_for=(Exception,), max_retries=3)  # pyrefly: ignore[not-callable]
def cleanup_backups(self) -> None:
    cutoff: datetime = datetime.now() - timedelta(days=settings.BACKUP_RETENTION_DAYS)
    roots: tuple[Path, Path, Path, Path] = (_PG_DIR, _REDIS_DIR, _NEO4J_DIR, _QDRANT_DIR)
    for root_dir in roots:
        entries: list[Path] = list(root_dir.iterdir())
        for candidate_path in entries:
            if candidate_path.is_file() and datetime.fromtimestamp(candidate_path.stat().st_ctime) < cutoff:
                candidate_path.unlink()
                logger.info(f"Deleted old backup {candidate_path}")
