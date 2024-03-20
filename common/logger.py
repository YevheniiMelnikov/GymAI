import sys

from loguru import logger

if not logger._core.handlers:
    logger.add(sys.stdout, level="INFO", format="{time} - {level} - {message}")
