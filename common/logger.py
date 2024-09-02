import os
import sys

from loguru import logger

debug_level = os.getenv("DEBUG_LEVEL", "INFO")
logger.configure(
    handlers=[
        {"sink": sys.stdout, "level": f"{debug_level}", "format": "{time:YYYY-MM-DD HH:mm:ss} - {level} - {message}"}
    ]
)
