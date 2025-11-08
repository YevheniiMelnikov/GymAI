from typing import Iterable, Sequence

from ai_coach.agent.knowledge.knowledge_base import KnowledgeSnippet
from config.app_settings import settings


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
) -> tuple[list[str], list[str], list[str]]:
    entry_ids: list[str] = []
    entries: list[str] = []
    datasets: list[str] = []
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
        entry_ids.append(entry_id)
        entries.append(text)
        datasets.append(dataset)
    return entry_ids, entries, datasets


def filter_entries_for_prompt(
    prompt: str,
    entry_ids: Sequence[str],
    entries: Sequence[str],
    datasets: Sequence[str],
) -> tuple[list[str], list[str], list[str]]:
    if not entry_ids or not entries:
        return list(entry_ids), list(entries), list(datasets)
    return list(entry_ids), list(entries), list(datasets)


def format_knowledge_entries(entry_ids: Sequence[str], entries: Sequence[str]) -> str:
    if not entry_ids or not entries:
        return ""
    formatted: list[str] = []
    for entry_id, text in zip(entry_ids, entries, strict=False):
        snippet = truncate_text(text, 500)
        formatted.append(f"{entry_id}: {snippet}")
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
        if value.startswith("kb_client_"):
            return (0, value)
        if value.startswith("kb_chat_"):
            return (1, value)
        if value == settings.COGNEE_GLOBAL_DATASET:
            return (2, value)
        return (3, value)

    unique.sort(key=_order)
    return unique
