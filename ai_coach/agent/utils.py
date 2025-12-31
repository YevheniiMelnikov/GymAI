from typing import Any, Final, Iterable

from ai_coach.agent.knowledge.context import current_kb, get_or_create_kb
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from ai_coach.schemas import ProgramPayload
from loguru import logger
from core.ai_coach.exercise_catalog import load_exercise_catalog, search_exercises
from core.schemas import Program


_LANGUAGE_NAME_MAP: Final[dict[str, str]] = {
    "uk": "Ukrainian",
    "ua": "Ukrainian",
    "ukr": "Ukrainian",
    "ua-ua": "Ukrainian",
    "uk-ua": "Ukrainian",
    "en": "English",
    "eng": "English",
    "en-us": "English",
    "ru": "Russian",
    "rus": "Russian",
    "ru-ru": "Russian",
}


def resolve_language_name(locale: str) -> str:
    normalized_locale: str = locale.strip().lower()
    mapped: str | None = _LANGUAGE_NAME_MAP.get(normalized_locale)
    if mapped:
        return mapped
    simplified: str = normalized_locale.replace("_", "-")
    mapped = _LANGUAGE_NAME_MAP.get(simplified)
    if mapped:
        return mapped
    return locale


class ProgramAdapter:
    """Utility to convert agent payloads to API models."""

    @staticmethod
    def to_domain(payload: ProgramPayload) -> Program:
        data = payload.model_dump(exclude={"schema_version"})
        exercises_by_day = _normalize_exercise_days(data.get("exercises_by_day"))
        if exercises_by_day:
            fill_missing_gif_keys(exercises_by_day)
            ensure_catalog_gif_keys(exercises_by_day)
            data["exercises_by_day"] = exercises_by_day
        if data.get("split_number") is None:
            data["split_number"] = len(getattr(payload, "exercises_by_day", []))
        return Program.model_validate(data)


def get_knowledge_base() -> KnowledgeBase:
    existing = current_kb()
    if existing is not None:
        return existing
    return get_or_create_kb()


def _normalize_exercise_days(raw_days: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_days, list):
        return []
    normalized: list[dict[str, Any]] = []
    for day in raw_days:
        if isinstance(day, dict):
            normalized.append(day)
        elif hasattr(day, "model_dump"):
            normalized.append(day.model_dump())
    return normalized


def fill_missing_gif_keys(exercises_by_day: Iterable[dict[str, Any]]) -> None:
    for day_entry in exercises_by_day:
        exercises = day_entry.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise_entry in exercises:
            if not isinstance(exercise_entry, dict):
                continue
            if exercise_entry.get("gif_key"):
                continue
            name_value = str(exercise_entry.get("name") or "").strip()
            if not name_value:
                continue
            matches = search_exercises(name_query=name_value, limit=1)
            if matches:
                exercise_entry["gif_key"] = matches[0].gif_key


def ensure_catalog_gif_keys(exercises_by_day: Iterable[dict[str, Any]]) -> None:
    entries = load_exercise_catalog()
    if not entries:
        raise ValueError("exercise_catalog_missing")
    catalog_keys = {entry.gif_key for entry in entries}
    missing = 0
    unknown = 0
    missing_samples: list[str] = []
    unknown_samples: list[str] = []
    for day_entry in exercises_by_day:
        exercises = day_entry.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise_entry in exercises:
            if not isinstance(exercise_entry, dict):
                continue
            gif_key = exercise_entry.get("gif_key")
            if not gif_key:
                missing += 1
                if len(missing_samples) < 3:
                    missing_samples.append(str(exercise_entry.get("name") or ""))
                continue
            if str(gif_key) not in catalog_keys:
                unknown += 1
                if len(unknown_samples) < 3:
                    unknown_samples.append(str(gif_key))
    if missing or unknown:
        logger.warning(
            "exercise_catalog_validation_failed missing={} unknown={} missing_samples={} unknown_samples={}",
            missing,
            unknown,
            missing_samples,
            unknown_samples,
        )
        raise ValueError(f"exercise_catalog_required missing={missing} unknown={unknown}")


__all__ = [
    "resolve_language_name",
    "ProgramAdapter",
    "get_knowledge_base",
    "fill_missing_gif_keys",
    "ensure_catalog_gif_keys",
]
