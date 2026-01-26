from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SCENARIOS_DIR = FIXTURES_DIR / "scenarios"
REPORTS_DIR = Path(__file__).resolve().parent / "reports"


def list_scenarios() -> list[str]:
    if not SCENARIOS_DIR.exists():
        return []
    scenarios = [path.name for path in SCENARIOS_DIR.iterdir() if path.is_dir()]
    return sorted(scenarios)


def apply_env_defaults() -> None:
    _load_env_files()
    _normalize_host_env()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.setdefault("LOGURU_LEVEL", "WARNING")
    os.environ.setdefault("COACH_AGENT_TEMPERATURE", os.getenv("COACH_AGENT_TEMPERATURE", "0"))
    os.environ.setdefault("EVAL_JUDGE_TEMPERATURE", os.getenv("EVAL_JUDGE_TEMPERATURE", "0"))


def _load_env_files() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:  # noqa: BLE001
        return
    repo_root = Path(__file__).resolve().parents[2]
    docker_env = repo_root / "docker" / ".env"
    root_env = repo_root / ".env"
    if docker_env.exists():
        load_dotenv(docker_env, override=False)
    if root_env.exists():
        load_dotenv(root_env, override=False)


def _normalize_host_env() -> None:
    db_host = os.getenv("DB_HOST", "")
    if db_host.strip().lower() == "db":
        os.environ["DB_HOST"] = "localhost"
        host_pg_port = os.getenv("HOST_PG_PORT", "").strip()
        if host_pg_port:
            os.environ["DB_PORT"] = host_pg_port
    coach_url = os.getenv("AI_COACH_URL", "").strip()
    coach_host = os.getenv("AI_COACH_HOST", "").strip().lower()
    host_coach_port = os.getenv("HOST_COACH_PORT", "").strip()
    coach_port = os.getenv("COACH_PORT", os.getenv("AI_COACH_PORT", "9000")).strip() or "9000"
    resolved_port = host_coach_port or coach_port
    if coach_url and "ai_coach" in coach_url:
        os.environ["AI_COACH_URL"] = coach_url.replace("ai_coach", "localhost")
    elif coach_host == "ai_coach":
        os.environ["AI_COACH_URL"] = f"http://localhost:{resolved_port}"
    if coach_host == "ai_coach":
        os.environ["AI_COACH_HOST"] = "localhost"
        os.environ["AI_COACH_PORT"] = resolved_port


def agent_temperature() -> str:
    return os.getenv("COACH_AGENT_TEMPERATURE", "")


def judge_temperature() -> str:
    return os.getenv("EVAL_JUDGE_TEMPERATURE", "")


def eval_concurrency() -> int:
    raw = os.getenv("EVAL_CONCURRENCY", "3").strip()
    try:
        value = int(raw)
    except ValueError:
        return 3
    return max(value, 1)


def judge_model_name() -> str:
    from config.app_settings import settings

    override = os.getenv("EVAL_JUDGE_MODEL", "").strip()
    if override:
        return override
    secondary = getattr(settings, "AI_COACH_SECONDARY_MODEL", None)
    if secondary:
        return str(secondary)
    return settings.AGENT_MODEL


def git_short_hash() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:  # noqa: BLE001
        return None
    output = result.stdout.strip()
    return output or None


def ai_coach_url() -> str:
    from config.app_settings import settings

    return settings.AI_COACH_URL


def agent_model() -> str:
    from config.app_settings import settings

    return settings.AGENT_MODEL


def settings_snapshot() -> dict[str, Any]:
    from config.app_settings import settings

    return {
        "ai_coach_url": settings.AI_COACH_URL,
        "agent_model": settings.AGENT_MODEL,
    }
