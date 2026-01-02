import re
from dataclasses import dataclass
from typing import Final, Iterable, Sequence

from ai_coach.agent.knowledge.schemas import KnowledgeSnippet
from config.app_settings import settings

_LINE_BREAKS: Final[tuple[str, ...]] = ("\r\n", "\r")
_DATA_IMAGE_TAG_RE: Final = re.compile(r"<data:image/[^>]+>", re.IGNORECASE)
_DATA_IMAGE_RE: Final = re.compile(r"data:image/[^\s)<>\"']+", re.IGNORECASE)


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


def sanitize_text(value: str) -> str:
    sanitized = _DATA_IMAGE_TAG_RE.sub("<image data removed>", value)
    sanitized = _DATA_IMAGE_RE.sub("[image data removed]", sanitized)
    return sanitized


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


@dataclass(frozen=True)
class KnowledgeEntry:
    entry_id: str
    text: str
    dataset: str


def truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    truncated = text[: limit + 1]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    return f"{truncated.rstrip()}..."


def shorten_for_summary(text: str, *, limit: int = 280) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    truncated = cleaned[: limit + 1]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    return f"{truncated.rstrip()}..."


def build_knowledge_entries(
    raw_entries: Sequence[KnowledgeSnippet | str],
    *,
    default_dataset: str | None = None,
) -> list[KnowledgeEntry]:
    entries: list[KnowledgeEntry] = []
    for index, raw in enumerate(raw_entries, start=1):
        if isinstance(raw, KnowledgeSnippet):
            if not raw.is_content():
                continue
            text = raw.text.strip()
            dataset = (raw.dataset or "").strip() if raw.dataset else ""
        else:
            text = str(raw or "").strip()
            dataset = default_dataset or ""
        if not text:
            continue
        entry_id = f"KB-{index}"
        entries.append(KnowledgeEntry(entry_id=entry_id, text=text, dataset=dataset))
    return entries


def filter_entries_for_prompt(
    _prompt: str,
    entries: Sequence[KnowledgeEntry],
) -> list[KnowledgeEntry]:
    if not entries:
        return list(entries)
    return list(entries)


def format_knowledge_entries(entries: Sequence[KnowledgeEntry]) -> str:
    if not entries:
        return ""
    formatted: list[str] = []
    for entry in entries:
        snippet = truncate_text(entry.text, 500)
        formatted.append(f"{entry.entry_id}: {snippet}")
    return "\n\n".join(formatted)


def unique_sources(datasets: Iterable[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for raw in datasets:
        alias = (raw or "").strip()
        if not alias or alias in seen:
            continue
        seen.add(alias)
        unique.append(alias)

    def _order(value: str) -> tuple[int, str]:
        if value.startswith("kb_profile_"):
            return (0, value)
        if value.startswith("kb_chat_"):
            return (1, value)
        if value == settings.COGNEE_GLOBAL_DATASET:
            return (2, value)
        return (3, value)

    unique.sort(key=_order)
    return unique
