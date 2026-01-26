from typing import Iterable

from .loader import load_exercise_catalog
from .models import ExerciseCatalogEntry


def filter_exercise_entries(
    entries: Iterable[ExerciseCatalogEntry],
    *,
    category: str | None = None,
    primary_muscles: Iterable[str] | None = None,
    secondary_muscles: Iterable[str] | None = None,
    equipment: Iterable[str] | None = None,
    name_query: str | None = None,
    limit: int | None = None,
) -> list[ExerciseCatalogEntry]:
    normalized_category = str(category or "").strip().lower() or None
    primary = {str(item).strip().lower() for item in (primary_muscles or []) if str(item or "").strip()}
    secondary = {str(item).strip().lower() for item in (secondary_muscles or []) if str(item or "").strip()}
    equipment_filter = {str(item).strip().lower() for item in (equipment or []) if str(item or "").strip()}
    query = str(name_query or "").strip().lower() or None
    limit_value = max(1, int(limit)) if limit is not None else None

    results: list[ExerciseCatalogEntry] = []
    for entry in entries:
        if normalized_category and entry.category != normalized_category:
            continue
        if primary:
            entry_primary = {item.lower() for item in entry.primary_muscles}
            if not entry_primary.intersection(primary):
                continue
        if secondary:
            entry_secondary = {item.lower() for item in entry.secondary_muscles}
            if not entry_secondary.intersection(secondary):
                continue
        if equipment_filter:
            entry_equipment = {item.lower() for item in entry.equipment}
            if not entry_equipment.intersection(equipment_filter):
                continue
        if query and not entry.matches_name(query):
            continue
        results.append(entry)
        if limit_value is not None and len(results) >= limit_value:
            break
    return results


def search_exercises(
    *,
    category: str | None = None,
    primary_muscles: Iterable[str] | None = None,
    secondary_muscles: Iterable[str] | None = None,
    equipment: Iterable[str] | None = None,
    name_query: str | None = None,
    limit: int | None = None,
) -> list[ExerciseCatalogEntry]:
    entries = load_exercise_catalog()
    return filter_exercise_entries(
        entries,
        category=category,
        primary_muscles=primary_muscles,
        secondary_muscles=secondary_muscles,
        equipment=equipment,
        name_query=name_query,
        limit=limit,
    )


def suggest_replacement_exercises(
    *,
    name_query: str | None,
    limit: int = 20,
) -> list[ExerciseCatalogEntry]:
    entries = load_exercise_catalog()
    query = str(name_query or "").strip()
    if not query:
        return list(entries)
    base_candidates = filter_exercise_entries(entries, name_query=query, limit=1)
    base = base_candidates[0] if base_candidates else None
    if base is None:
        return filter_exercise_entries(entries, name_query=query, limit=None)

    normalized_category = base.category
    if normalized_category in {"conditioning", "health"}:
        return [
            entry for entry in entries if entry.category == normalized_category and entry.canonical != base.canonical
        ]

    base_primary = {item.lower() for item in base.primary_muscles}
    return [
        entry
        for entry in entries
        if entry.category == normalized_category
        and entry.canonical != base.canonical
        and base_primary.intersection({item.lower() for item in entry.primary_muscles})
    ]


__all__ = ["filter_exercise_entries", "search_exercises", "suggest_replacement_exercises"]
