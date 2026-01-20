import re
from typing import Any, Final, Iterable, Mapping

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


_AUX_EXERCISE_KINDS: Final[set[str]] = {"warmup", "cardio"}
_CARDIO_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:\bcardio\b|кардио|бег|дорожк|вело|велотрен|bike|biking|cycling|rowing\s*machine|rower|erg|concept2|гребл|эллипс|скакал|jump\s*rope)",
    flags=re.IGNORECASE,
)
_MINUTES_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?P<minutes>\d{1,3})\s*(?:мин\.?|минут(?:ы)?|minutes?|mins?|m)\b",
    flags=re.IGNORECASE,
)


def _exercise_kind(entry: Mapping[str, Any]) -> str:
    return str(entry.get("kind") or "").strip().lower()


def _is_aux_exercise(entry: Mapping[str, Any]) -> bool:
    return _exercise_kind(entry) in _AUX_EXERCISE_KINDS


def _label_warmup(language: str) -> str:
    code = (language or "").strip().lower()
    if code in {"ru", "rus"}:
        return "Разминка"
    if code in {"uk", "ua"}:
        return "Розминка"
    return "Warm-up"


def _label_cardio(language: str) -> str:
    code = (language or "").strip().lower()
    if code in {"ru", "rus"}:
        return "Кардио"
    if code in {"uk", "ua"}:
        return "Кардіо"
    return "Cardio"


def _looks_like_cardio(name: str) -> bool:
    return bool(_CARDIO_PATTERN.search(name or ""))


def _maybe_extract_minutes(text: str) -> int | None:
    match = _MINUTES_PATTERN.search(text or "")
    if not match:
        return None
    try:
        minutes = int(match.group("minutes"))
    except (TypeError, ValueError):
        return None
    return minutes if minutes > 0 else None


def apply_workout_aux_rules(
    exercises_by_day: list[dict[str, Any]],
    *,
    language: str,
    workout_location: str | None,
    wishes: str | None,
    prompt: str | None,
    profile_context: str | None,
) -> None:
    """
    Enforce workout plan UX rules:
    - First exercise is always a text-only warm-up block (no catalog search, no gifs, no sets/reps).
    - Optional cardio, if present/needed, is always the last entry as a text-only block.
    """

    def warmup_lines() -> list[str]:
        label = _label_warmup(language)
        lines = [label]
        location = (workout_location or "").strip().lower()
        code = (language or "").strip().lower()
        gym_like = location in {"gym", "strength"}
        if code in {"ru", "rus"}:
            lines.extend(
                [
                    "• Суставная разминка 3–5 мин (шея/плечи/локти/таз/колени/голеностоп).",
                    (
                        "• Лёгкое кардио 5–8 мин (дорожка/вело/эллипс), интенсивность 3–5/10."
                        if gym_like
                        else "• Лёгкое кардио 3–6 мин (ходьба на месте/step-ups), интенсивность 3–5/10."
                    ),
                    "• Динамическая мобилизация под тренировку (бедро/тазобедренный/плечи/грудной отдел).",
                ]
            )
            if any(token for token in (wishes, prompt, profile_context) if token and "боль" in token.lower()):
                lines.append("• Избегай болевых ощущений; при дискомфорте снизь амплитуду и темп.")
        elif code in {"uk", "ua"}:
            lines.extend(
                [
                    "• Суглобова розминка 3–5 хв (шия/плечі/лікті/таз/коліна/гомілкостоп).",
                    (
                        "• Легке кардіо 5–8 хв (доріжка/вело/еліпс), інтенсивність 3–5/10."
                        if gym_like
                        else "• Легке кардіо 3–6 хв (ходьба на місці/step-ups), інтенсивність 3–5/10."
                    ),
                    "• Динамічна мобілізація під тренування (стегно/тазостегновий/плечі/грудний відділ).",
                ]
            )
            if any(token for token in (wishes, prompt, profile_context) if token and "біль" in token.lower()):
                lines.append("• Уникай больових відчуттів; при дискомфорті зменш амплітуду й темп.")
        else:
            lines.extend(
                [
                    "• Joint warm-up 3–5 min (neck/shoulders/elbows/hips/knees/ankles).",
                    (
                        "• Light cardio 5–8 min (treadmill/bike/elliptical), intensity 3–5/10."
                        if gym_like
                        else "• Light cardio 3–6 min (marching/step-ups), intensity 3–5/10."
                    ),
                    "• Dynamic mobility relevant to today’s session (hips/shoulders/thoracic spine).",
                ]
            )
            if any(token for token in (wishes, prompt, profile_context) if token and "pain" in token.lower()):
                lines.append("• Avoid pain; if discomfort appears, reduce range of motion and tempo.")
        return lines

    def should_extract_cardio_fallback(exercise: Mapping[str, Any]) -> bool:
        kind = _exercise_kind(exercise)
        if kind:
            return False
        name = str(exercise.get("name") or "").strip()
        if not _looks_like_cardio(name):
            return False
        minutes = _maybe_extract_minutes(name) or _maybe_extract_minutes(str(exercise.get("reps") or ""))
        if minutes is not None:
            return True
        return "cardio" in name.casefold() or "кардио" in name.casefold()

    def build_warmup_exercise() -> dict[str, Any]:
        return {
            "kind": "warmup",
            "name": "\n".join(warmup_lines()),
            "sets": "—",
            "reps": "—",
            "weight": None,
            "set_id": None,
            "gif_key": None,
            "drop_set": False,
            "superset_id": None,
            "superset_order": None,
            "sets_detail": None,
        }

    def build_cardio_exercise(
        *,
        removed_cardio: list[dict[str, Any]],
        location: str | None,
    ) -> dict[str, Any]:
        label = _label_cardio(language)
        type_hint = ""
        minutes: int | None = None
        for entry in removed_cardio[:3]:
            candidate_name = str(entry.get("name") or "").strip()
            if candidate_name and not type_hint:
                type_hint = candidate_name
            if minutes is None:
                minutes = _maybe_extract_minutes(candidate_name) or _maybe_extract_minutes(str(entry.get("reps") or ""))

        if not type_hint:
            loc = (location or "").strip().lower()
            type_hint = "Bike / treadmill / elliptical" if loc in {"gym", "strength"} else "Brisk walk / step-ups"
            if language in {"ru", "rus"}:
                type_hint = "Вело / дорожка / эллипс" if loc in {"gym", "strength"} else "Быстрая ходьба / степ-апы"
            elif language in {"uk", "ua"}:
                type_hint = "Вело / доріжка / еліпс" if loc in {"gym", "strength"} else "Швидка ходьба / степ-апи"

        if minutes is None:
            minutes = 10

        if language in {"ru", "rus"}:
            details = [
                f"{label}",
                f"• Тип: {type_hint}.",
                f"• Длительность: {minutes}–20 мин.",
                "• Интенсивность: умеренная (RPE 5–7/10), без задыхания.",
            ]
        elif language in {"uk", "ua"}:
            details = [
                f"{label}",
                f"• Тип: {type_hint}.",
                f"• Тривалість: {minutes}–20 хв.",
                "• Інтенсивність: помірна (RPE 5–7/10), без задухи.",
            ]
        else:
            details = [
                f"{label}",
                f"• Type: {type_hint}.",
                f"• Duration: {minutes}–20 min.",
                "• Intensity: moderate (RPE 5–7/10), no gasping.",
            ]

        return {
            "kind": "cardio",
            "name": "\n".join(details),
            "sets": "—",
            "reps": "—",
            "weight": None,
            "set_id": None,
            "gif_key": None,
            "drop_set": False,
            "superset_id": None,
            "superset_order": None,
            "sets_detail": None,
        }

    for day_entry in exercises_by_day:
        exercises = day_entry.get("exercises")
        if not isinstance(exercises, list) or not exercises:
            continue
        day_exercises = [ex for ex in exercises if isinstance(ex, dict)]
        removed_cardio: list[dict[str, Any]] = []
        kept: list[dict[str, Any]] = []
        for ex in day_exercises:
            if _exercise_kind(ex) == "cardio" or should_extract_cardio_fallback(ex):
                removed_cardio.append(ex)
                continue
            kept.append(ex)

        warmup = build_warmup_exercise()
        if kept and _exercise_kind(kept[0]) == "warmup":
            kept[0] = warmup
        else:
            kept.insert(0, warmup)

        if removed_cardio:
            kept.append(build_cardio_exercise(removed_cardio=removed_cardio, location=workout_location))

        day_entry["exercises"] = kept


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
            if _is_aux_exercise(exercise_entry):
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
            if _is_aux_exercise(exercise_entry):
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
    "apply_workout_aux_rules",
]
