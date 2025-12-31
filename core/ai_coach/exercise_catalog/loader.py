import json
from functools import lru_cache
from pathlib import Path

from loguru import logger

from .models import ExerciseCatalogEntry


def _normalize_string_list(values: object) -> tuple[str, ...]:
    if not isinstance(values, list):
        return tuple()
    normalized = [str(item).strip() for item in values if str(item or "").strip()]
    return tuple(normalized)


def _load_catalog_path() -> Path:
    return Path(__file__).resolve().parent / "exercises.jsonl"


def _parse_entry(raw: dict[str, object]) -> ExerciseCatalogEntry | None:
    gif_key = str(raw.get("gif_key") or "").strip()
    canonical = str(raw.get("canonical") or "").strip()
    category = str(raw.get("category") or "").strip().lower()
    if not gif_key or not canonical or not category:
        return None
    return ExerciseCatalogEntry(
        gif_key=gif_key,
        canonical=canonical,
        aliases=_normalize_string_list(raw.get("aliases")),
        category=category,
        primary_muscles=_normalize_string_list(raw.get("primary_muscles")),
        secondary_muscles=_normalize_string_list(raw.get("secondary_muscles")),
    )


@lru_cache(maxsize=1)
def load_exercise_catalog() -> tuple[ExerciseCatalogEntry, ...]:
    path = _load_catalog_path()
    if not path.exists():
        logger.warning(f"exercise_catalog_missing path={path}")
        return tuple()
    entries: list[ExerciseCatalogEntry] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw_line = line.strip()
            if not raw_line:
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                logger.warning(f"exercise_catalog_line_invalid error={exc}")
                continue
            if not isinstance(payload, dict):
                continue
            entry = _parse_entry(payload)
            if entry is None:
                continue
            entries.append(entry)
    return tuple(entries)


__all__ = ["load_exercise_catalog"]
