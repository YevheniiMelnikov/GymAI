import sys

from loguru import logger

from common.settings import settings

logger.configure(
    handlers=[
        {
            "sink": sys.stdout,
            "level": f"{settings.DEBUG_LEVEL}",
            "format": "{time:YYYY-MM-DD HH:mm:ss} - {level} - {message}",
        }
    ]
)
