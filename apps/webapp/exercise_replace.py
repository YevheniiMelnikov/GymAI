import json
import re
from datetime import datetime
from typing import Any, Protocol, TypedDict

from pydantic import BaseModel
from django.core.cache import cache
from django.utils import timezone

from config.app_settings import settings

EXERCISE_ID_PATTERN = re.compile(r"^ex-(\d+)-(\d+)$")
MARKDOWN_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"</?[^>]+>")


class ExerciseSetPayload(TypedDict):
    reps: int
    weight: float


class SetsUpdatePayload(TypedDict):
    weight_unit: str | None
    sets: list[ExerciseSetPayload]


class UpdateExercisePayload(SetsUpdatePayload):
    program_id: int
    exercise_id: str


class UpdateSubscriptionExercisePayload(SetsUpdatePayload):
    subscription_id: int
    exercise_id: str


class ReplaceExerciseSet(BaseModel):
    reps: int
    weight: float
    weight_unit: str | None = None


class ReplaceExercise(BaseModel):
    name: str
    sets: str | int | None = None
    reps: str | int | None = None
    weight: str | None = None
    gif_key: str | None = None
    sets_detail: list[ReplaceExerciseSet]


class ReplaceExerciseResponse(BaseModel):
    exercise: ReplaceExercise


class ProfilePayload(Protocol):
    id: int
    language: str | None
    gender: str | None
    born_in: int | None
    weight: int | None
    height: int | None
    health_notes: str | None
    workout_experience: str | None
    workout_goals: str | None
    workout_location: str | None


def _limit_key(prefix: str, identifier: int) -> str:
    return f"exercise_replace_limit:{prefix}:{identifier}"


def _subscription_month_key(subscription_id: int, now: datetime) -> str:
    return f"exercise_replace_limit:subscription:{subscription_id}:{now:%Y%m}"


def _month_ttl_seconds(now: datetime) -> int:
    if now.month == 12:
        next_month = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        next_month = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((next_month - now).total_seconds()))


def _consume_limit(key: str, limit: int, *, ttl: int | None) -> bool:
    if limit <= 0:
        return False
    cache.add(key, 0, timeout=ttl)
    try:
        current = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=ttl)
        current = 1
    if current > limit:
        try:
            cache.decr(key)
        except ValueError:
            pass
        return False
    return True


def consume_program_replace_limit(program_id: int) -> bool:
    return _consume_limit(
        _limit_key("program", program_id),
        settings.EXERCISE_REPLACE_PROGRAM_LIMIT,
        ttl=None,
    )


def consume_subscription_replace_limit(subscription_id: int, *, period: str) -> bool:
    if period in {"6m", "12m"}:
        now = timezone.now()
        return _consume_limit(
            _subscription_month_key(subscription_id, now),
            settings.EXERCISE_REPLACE_SUBSCRIPTION_MONTHLY_LIMIT,
            ttl=_month_ttl_seconds(now),
        )
    return _consume_limit(
        _limit_key("subscription", subscription_id),
        settings.EXERCISE_REPLACE_SUBSCRIPTION_LIMIT,
        ttl=None,
    )


def format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def format_range(values: list[float]) -> str:
    min_value = min(values)
    max_value = max(values)
    if min_value == max_value:
        return format_number(max_value)
    return f"{format_number(min_value)}-{format_number(max_value)}"


def apply_sets_update(exercise_entry: dict[str, Any], payload: SetsUpdatePayload) -> None:
    sets_payload = payload["sets"]
    reps_values = [float(item["reps"]) for item in sets_payload]
    weights = [float(item["weight"]) for item in sets_payload]
    weight_unit = payload.get("weight_unit") or ""

    reps_summary = format_range(reps_values)
    weight_summary = None
    if any(value > 0 for value in weights):
        weight_summary = format_range(weights)
        if weight_unit:
            weight_summary = f"{weight_summary} {weight_unit}"

    exercise_entry["sets"] = str(len(sets_payload))
    exercise_entry["reps"] = reps_summary
    exercise_entry["weight"] = weight_summary
    exercise_entry["sets_detail"] = [
        {"reps": int(item["reps"]), "weight": float(item["weight"]), "weight_unit": weight_unit}
        for item in sets_payload
    ]


def resolve_profile_payload(profile: ProfilePayload) -> dict[str, Any]:
    return {
        "id": profile.id,
        "language": profile.language,
        "gender": profile.gender,
        "born_in": profile.born_in,
        "weight": profile.weight,
        "height": profile.height,
        "health_notes": profile.health_notes,
        "workout_experience": profile.workout_experience,
        "workout_goals": profile.workout_goals,
        "workout_location": profile.workout_location,
    }


def resolve_exercise_entry(exercises_by_day: list[dict[str, Any]], exercise_id: str) -> dict[str, Any] | None:
    match = EXERCISE_ID_PATTERN.match(exercise_id)
    if match:
        day_index = int(match.group(1)) - 1
        exercise_index = int(match.group(2))
        if 0 <= day_index < len(exercises_by_day):
            day_entry = exercises_by_day[day_index]
            day_exercises = day_entry.get("exercises", [])
            if isinstance(day_exercises, list) and 0 <= exercise_index < len(day_exercises):
                entry = day_exercises[exercise_index]
                return entry if isinstance(entry, dict) else None

    for day_entry in exercises_by_day:
        day_exercises = day_entry.get("exercises", [])
        if not isinstance(day_exercises, list):
            continue
        for exercise_entry in day_exercises:
            entry_id = exercise_entry.get("set_id")
            if entry_id is not None and str(entry_id) == exercise_id:
                return exercise_entry if isinstance(exercise_entry, dict) else None
    return None


def extract_json_payload(raw_text: str) -> dict[str, Any]:
    raw = str(raw_text or "")
    if not raw:
        raise ValueError("empty_payload")
    sanitized = HTML_TAG_RE.sub("", raw)
    match = MARKDOWN_BLOCK_RE.search(sanitized)
    if match:
        sanitized = match.group(1).strip()
    sanitized = sanitized.replace("\r\n", "\n").strip()
    start = sanitized.find("{")
    end = sanitized.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("json_not_found")
    return json.loads(sanitized[start : end + 1])
