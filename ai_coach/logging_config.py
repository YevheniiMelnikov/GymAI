import logging
import os
import sys
import time
import warnings
from dataclasses import asdict, is_dataclass
from types import FrameType
from typing import Any, Dict, MutableMapping

from loguru import logger


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except Exception:
            level = record.levelno
        frame: FrameType | None = logging.currentframe()
        depth = 2
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


__all__ = ["configure_logging", "SamplingFilter", "log_once"]


class SamplingFilter(logging.Filter):
    """Sampling filter suppressing duplicate messages within a TTL window."""

    def __init__(self, ttl: float = 30.0) -> None:
        super().__init__()
        self.ttl = float(ttl)
        self._state: Dict[str, tuple[float, int]] = {}

    def _allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        if key not in self._state:
            self._state[key] = (now, 0)
            return True, 0

        last_ts, suppressed = self._state[key]
        if now - last_ts >= self.ttl:
            self._state[key] = (now, 0)
            return True, suppressed

        self._state[key] = (last_ts, suppressed + 1)
        return False, 0

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401 - stdlib signature
        key = getattr(record, "sampling_key", record.getMessage())
        allowed, suppressed = self._allow(key)
        if allowed and suppressed:
            record.msg = f"{record.getMessage()} (suppressed={suppressed})"
            record.args = ()
        return allowed

    def __call__(self, record: MutableMapping[str, Any]) -> bool:
        message: str = record.get("message", "")
        key = record.get("extra", {}).get("sampling_key") or message
        allowed, suppressed = self._allow(str(key))
        if allowed and suppressed:
            record["message"] = f"{message} (suppressed={suppressed})"
        return allowed


class HealthAccessFilter(logging.Filter):
    """Filter out noisy access logs for periodic health checks."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - fallback best-effort
            message = ""
        return "GET /health" not in message


class CogneeTelemetryFilter(logging.Filter):
    """Filter noisy Cognee telemetry logs when disabled."""

    def __init__(self, enabled: bool) -> None:
        super().__init__()
        self.enabled = enabled

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        if self.enabled:
            return True
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - fallback best-effort
            return True
        lowered = message.lower()
        if any(
            token in lowered
            for token in (
                "successfully connected to redis",
                "successfully saved q&a to session cache",
            )
        ):
            return record.levelno < logging.INFO
        if record.name != "logging" and "run_tasks" not in lowered and "pipeline run" not in lowered:
            return True
        if any(
            token in lowered
            for token in (
                "pipeline run started",
                "pipeline run completed",
                "coroutine task started",
                "coroutine task completed",
                "run_tasks_base",
                "run_tasks_with_telemetry",
            )
        ):
            return record.levelno < logging.INFO
        if message.startswith("{'event':") and "pipeline run" in lowered:
            return record.levelno < logging.INFO
        return True


class AiohttpSessionFilter(logging.Filter):
    """Suppress aiohttp unclosed session warnings in INFO logs."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - fallback best-effort
            return True
        lowered = message.lower()
        if "unclosed client session" in lowered or "unclosed connector" in lowered:
            return record.levelno < logging.INFO
        return True


_CONFIGURED = False
_LOG_ONCE_STATE: dict[str, dict[str, float | int]] = {}


def configure_logging() -> None:
    """Configure logging across ai_coach with consistent sampling and levels."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    sampling_filter = SamplingFilter(ttl=30.0)

    verbose = os.getenv("AI_COACH_VERBOSE_KB", "").strip() == "1"
    telemetry_enabled = (
        os.getenv("AI_COACH_COGNEE_TELEMETRY", "").strip() == "1" or os.getenv("AI_COACH_NOISY_LOGS", "").strip() == "1"
    )
    level_name = "DEBUG" if verbose else "INFO"
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    logger.remove()
    logger.add(sys.stderr, level=level_name, colorize=True, backtrace=False, diagnose=False, format=log_format)

    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("cognee").setLevel(logging.WARNING)
    warnings.filterwarnings(
        "ignore",
        message="Api key is used with an insecure connection.",
        category=UserWarning,
    )

    intercept_handler = InterceptHandler()
    intercept_handler.addFilter(sampling_filter)
    intercept_handler.addFilter(CogneeTelemetryFilter(telemetry_enabled))
    intercept_handler.addFilter(AiohttpSessionFilter())
    logging.basicConfig(handlers=[intercept_handler], level=logging.INFO, force=True)

    kb_logger_names = (
        "ai_coach",
        "ai_coach.agent",
        "ai_coach.agent.knowledge",
    )
    kb_level = logging.DEBUG if verbose else logging.INFO
    for name in kb_logger_names:
        target = logging.getLogger(name)
        target.handlers = []
        target.setLevel(kb_level)
        target.propagate = True

    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers = []
    access_logger.setLevel(logging.INFO)
    access_logger.addFilter(HealthAccessFilter())
    access_logger.propagate = True

    noisy_loggers = (
        "uvicorn",
        "uvicorn.error",
        "fastapi",
        "sqlalchemy",
        "httpx",
        "asyncio",
        "OntologyAdapter",
        "CogneeGraph",
        "GraphCompletionRetriever",
        "Neo4jAdapter",
    )
    for name in noisy_loggers:
        target = logging.getLogger(name)
        target.handlers = []
        level = logging.ERROR if name == "GraphCompletionRetriever" else logging.WARNING
        target.setLevel(level)
        target.propagate = True

    if not verbose:
        kb_noisy = (
            "ai_coach.agent.knowledge.utils.datasets",
            "ai_coach.agent.knowledge.utils.storage",
            "ai_coach.agent.knowledge.utils.storage_helpers",
            "ai_coach.agent.knowledge.gdrive_knowledge_loader",
            "ai_coach.agent.knowledge.knowledge_base",
        )
        for name in kb_noisy:
            target = logging.getLogger(name)
            target.handlers = []
            target.setLevel(logging.WARNING)
            target.propagate = True

    _CONFIGURED = True


def log_once(
    msg_key: str,
    *,
    level: int = logging.INFO,
    ttl: float = 120.0,
    message: str | None = None,
    logger_obj: Any | None = None,
    **fields: Any,
) -> None:
    """Log a structured message at most once per ttl seconds."""
    global _LOG_ONCE_STATE

    now = time.monotonic()
    state = _LOG_ONCE_STATE.get(msg_key)
    if state is not None:
        window = float(state.get("ttl", ttl))
        if now - float(state.get("ts", 0.0)) < window:
            state["count"] = int(state.get("count", 0)) + 1
            return
        suppressed = int(state.get("count", 0))
    else:
        suppressed = 0

    _LOG_ONCE_STATE[msg_key] = {"ts": now, "count": 0, "ttl": ttl}

    parts = [message or msg_key]
    for key, value in fields.items():
        if value is None:
            continue
        if is_dataclass(value):
            value = asdict(value)
        value_text = str(value)
        if " " in value_text and not value_text.startswith(("'", '"')):
            value_text = f'"{value_text}"'
        parts.append(f"{key}={value_text}")

    if suppressed:
        parts.append(f"suppressed={suppressed}")

    payload = " ".join(parts)
    target_logger = logger_obj or logger
    level_name = logging.getLevelName(level)
    target_logger.log(level_name, payload)
