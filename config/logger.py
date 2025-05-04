import logging
import sys
from loguru import logger

from config.env_settings import Settings


def configure_loguru():
    logger.remove()
    logger.configure(
        handlers=[  # type: ignore
            {
                "sink": sys.stdout,
                "level": "DEBUG",
                "format": "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",  # noqa
                "colorize": True,
            },
            {
                "sink": "gym_bot.log",
                "level": Settings.LOG_LEVEL,
                "serialize": False,
                "format": "{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
                "rotation": "100 MB",
                "retention": "30 days",
                "compression": "zip",
                "enqueue": True,
            },
        ]
    )


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

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(loguru_level, record.getMessage())
