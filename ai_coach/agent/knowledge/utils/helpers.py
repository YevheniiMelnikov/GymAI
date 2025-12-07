from typing import Final

_LINE_BREAKS: Final[tuple[str, ...]] = ("\r\n", "\r")


def normalize_text(value: str | None) -> str:
    """Trim text and normalize line endings to LF."""
    if not value:
        return ""
    stripped = value.strip()
    if not stripped:
        return ""
    normalized = stripped
    for mark in _LINE_BREAKS:
        normalized = normalized.replace(mark, "\n")
    return normalized


def needs_cognee_setup(exc: Exception) -> bool:
    from sqlite3 import OperationalError as SQLiteOperationalError

    try:
        from sqlalchemy.exc import OperationalError as SAOperationalError
    except ImportError:
        SAOperationalError = None
    try:
        from cognee.infrastructure.databases.exceptions import DatabaseNotCreatedError
    except ImportError:
        DatabaseNotCreatedError = None

    if DatabaseNotCreatedError and isinstance(exc, DatabaseNotCreatedError):
        return True
    if isinstance(exc, SQLiteOperationalError):
        return True
    if SAOperationalError and isinstance(exc, SAOperationalError):
        message = str(exc).lower()
        return any(token in message for token in ("await setup", "no such table", "database not created"))
    message = str(exc).lower()
    return any(token in message for token in ("await setup", "no such table", "database not created"))
