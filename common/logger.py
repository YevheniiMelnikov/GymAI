import sys
from loguru import logger

logger.configure(
    handlers=[
        {
            "sink": sys.stdout,
            "level": "INFO",
            "format": "{time:YYYY-MM-DD HH:mm:ss} - {level} - {message}"
        }
    ]
)
