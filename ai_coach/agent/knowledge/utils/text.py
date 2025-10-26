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
