import logging
import os
import sys
import time
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, MutableMapping

from loguru import logger


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except Exception:
            level = record.levelno
        frame = logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == logging.__file__:
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
        last_ts, suppressed = self._state.get(key, (0.0, 0))
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


_CONFIGURED = False
_LOG_ONCE_STATE: dict[str, dict[str, float | int]] = {}


def configure_logging() -> None:
    """Configure logging across ai_coach with consistent sampling and levels."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    sampling_filter = SamplingFilter(ttl=30.0)

    verbose = os.getenv("AI_COACH_VERBOSE_KB", "").strip() == "1"
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

    intercept_handler = InterceptHandler()
    intercept_handler.addFilter(sampling_filter)
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
    )
    for name in noisy_loggers:
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
