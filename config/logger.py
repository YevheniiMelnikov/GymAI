import logging
import sys
import types
from loguru import logger
from config.app_settings import settings


def configure_loguru():
    logger.remove()
    logger.configure(
        handlers=[  # type: ignore
            {
                "sink": sys.stdout,
                "level": "DEBUG",
                "format": (
                    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                    "<level>{level}</level> | "
                    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                    "<level>{message}</level>"
                ),
                "colorize": True,
            },
        ]
    )

    _suppress_third_party_logs()


def _suppress_third_party_logs() -> None:
    base_suppress_map: dict[str, str] = {
        "cognee": "WARNING",
        "cognee.shared.logging_utils": "ERROR",
        "litellm": "WARNING",
        "LiteLLM": "WARNING",
        "LiteLLMEmbeddingEngine": "WARNING",
        "openai": "WARNING",
        "stainless_sdk": "WARNING",
        "instructor": "WARNING",
        "langfuse": "ERROR",
        "google": "WARNING",
        "googleapiclient": "WARNING",
        "httpx": "WARNING",
        "httpcore": "WARNING",
        "matplotlib": "ERROR",
        "urllib3": "WARNING",
        "asyncio": "WARNING",
        "aiogram": "WARNING",
        "amqp": "WARNING",
        "amqp.connection": "WARNING",
        "kombu.connection": "WARNING",
    }

    celery_verbose_map: dict[str, str] = {
        "amqp": "INFO",
        "amqp.connection": "INFO",
        "kombu.connection": "INFO",
        "celery": "INFO",
        "celery.app.trace": "INFO",
    }

    for logger_name, level in base_suppress_map.items():
        effective_level: str = celery_verbose_map.get(logger_name, level) if settings.LOG_VERBOSE_CELERY else level
        logging.getLogger(logger_name).setLevel(effective_level)

    if settings.LOG_VERBOSE_CELERY:
        for logger_name, level in celery_verbose_map.items():
            logging.getLogger(logger_name).setLevel(level)

    # silence noisy info logs from libraries using the root logger
    logging.getLogger().setLevel("WARNING")


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "loguru": {
            "level": "DEBUG",
            "class": "config.logger.InterceptHandler",
        },
    },
    "root": {
        "handlers": ["loguru"],
        "level": "WARNING",
    },
    "loggers": {
        "django": {
            "handlers": ["loguru"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["loguru"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            loguru_level = logger.level(record.levelname).name
        except Exception:
            loguru_level = record.levelno

        frame: types.FrameType | None = logging.currentframe()
        depth = 2
        logging_file = getattr(logging, "__file__", None)
        while frame and logging_file and frame.f_code.co_filename == logging_file:
            frame = frame.f_back
            depth += 1

        if record.levelno >= _resolve_level(settings.LOG_LEVEL):
            logger.opt(depth=depth, exception=record.exc_info).log(loguru_level, record.getMessage())


def _resolve_level(level: int | str) -> int:
    if isinstance(level, int):
        return level

    mapping = logging.getLevelNamesMapping()
    resolved = mapping.get(level.upper())
    if isinstance(resolved, int):
        return resolved

    raise ValueError(f"Unknown log level: {level}")
