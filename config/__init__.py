import os


def configure_loguru() -> None:
    """Configure logging with lazy import to avoid early settings access."""
    from config.logger import configure_loguru as _configure_loguru

    _configure_loguru()


if os.environ.get("SECRET_KEY"):
    configure_loguru()
