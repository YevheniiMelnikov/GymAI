import logging
import sys
import types
from loguru import logger
from config.env_settings import settings


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
            {
                "sink": "gym_bot.log",
                "level": settings.LOG_LEVEL,
                "serialize": False,
                "format": "{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
                "rotation": "100 MB",
                "retention": "30 days",
                "compression": "zip",
                "enqueue": True,
            },
        ]
    )

    _suppress_third_party_logs()


def _suppress_third_party_logs():
    suppress_map = {
        "cognee": "WARNING",
        "cognee.shared.logging_utils": "ERROR",
        "litellm": "WARNING",
        "LiteLLM": "WARNING",
        "httpx": "WARNING",
        "httpcore": "WARNING",
        "matplotlib": "ERROR",
        "urllib3": "WARNING",
        "asyncio": "WARNING",
    }

    for logger_name, level in suppress_map.items():
        logging.getLogger(logger_name).setLevel(level)


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
        "level": "DEBUG",
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

        if record.levelno >= logging.getLevelName(settings.LOG_LEVEL):
            logger.opt(depth=depth, exception=record.exc_info).log(loguru_level, record.getMessage())
