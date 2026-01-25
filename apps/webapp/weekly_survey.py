from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
from typing import Any, Callable, Sequence, TypedDict
from zoneinfo import ZoneInfo

from celery import chain
from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator

from apps.workout_plans.progress_types import (
    ProgressDay,
    ProgressExercise,
    ProgressSet,
    ProgressSnapshotPayload,
)
from config.app_settings import settings
from core.ai_coach import AiPlanUpdatePayload
from core.enums import WorkoutPlanType, WorkoutLocation
from core.tasks.ai_coach import (
    handle_ai_plan_failure,
    notify_ai_plan_ready_task,
    update_ai_workout_plan,
)


class WeeklySurveySet(BaseModel):
    reps: int = Field(ge=1)
    weight: float = Field(ge=0)
    weight_unit: str = "kg"

    @field_validator("weight_unit", mode="before")
    @classmethod
    def _normalize_weight_unit(cls, value: str | None) -> str:
        normalized = str(value or "").strip()
        return normalized or "kg"


class WeeklySurveyExercise(BaseModel):
    id: str
    name: str
    difficulty: int = Field(ge=0, le=100)
    comment: str | None = None
    sets_detail: list[WeeklySurveySet] | None = None

    @field_validator("comment")
    @classmethod
    def _normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed if trimmed else None


class WeeklySurveyDay(BaseModel):
    id: str
    title: str | None = None
    skipped: bool = False
    exercises: list[WeeklySurveyExercise] = Field(default_factory=list)


class WeeklySurveyPayload(BaseModel):
    subscription_id: int
    days: list[WeeklySurveyDay]


@dataclass(frozen=True)
class SurveyFeedbackContext:
    workout_goals: str | None
    workout_experience: str | None
    plan_age_weeks: int | None


def resolve_plan_age_weeks(updated_at: Any) -> int | None:
    if not updated_at:
        return None
    if isinstance(updated_at, datetime):
        updated = updated_at
    else:
        try:
            updated = datetime.fromisoformat(str(updated_at))
        except Exception:  # noqa: BLE001
            return None
    tz = ZoneInfo(settings.TIME_ZONE)
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=tz)
    now = datetime.now(tz)
    delta_days = max(0, (now - updated).days)
    return max(1, (delta_days // 7) or 1)


def compute_plan_hash(exercises_by_day: list[dict[str, Any]]) -> str | None:
    identifiers: list[str] = []
    for day_data in exercises_by_day:
        exercises = day_data.get("exercises", [])
        if not isinstance(exercises, list):
            continue
        for entry in exercises:
            if not isinstance(entry, dict):
                continue
            kind = str(entry.get("kind") or "").strip().lower()
            if kind in {"warmup", "cardio"}:
                continue
            gif_key = entry.get("gif_key")
            if gif_key:
                identifiers.append(f"gif:{gif_key}")
                continue
            set_id = entry.get("set_id")
            if set_id is not None:
                identifiers.append(f"id:{set_id}")
                continue
            name = str(entry.get("name") or "").strip().lower()
            if name:
                identifiers.append(f"name:{name}")
    if not identifiers:
        return None
    identifiers.sort()
    digest = hashlib.sha256("|".join(identifiers).encode("utf-8")).hexdigest()
    return digest


def resolve_progress_week_start(now: datetime | None = None) -> date:
    tz = ZoneInfo(settings.TIME_ZONE)
    current = (now or datetime.now(tz)).astimezone(tz)
    return current.date() - timedelta(days=current.weekday())


def _parse_numeric_max(value: Any, *, fallback: float = 0.0) -> float:
    if value is None:
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value)
    if not raw:
        return fallback
    numbers: list[float] = []
    current = ""
    for char in raw:
        if char.isdigit() or char in {".", ","}:
            current += "." if char == "," else char
        elif current:
            try:
                numbers.append(float(current))
            except ValueError:
                pass
            current = ""
    if current:
        try:
            numbers.append(float(current))
        except ValueError:
            pass
    if not numbers:
        return fallback
    return max(numbers)


def _extract_sets_from_entry(entry: dict[str, Any] | None) -> list[WeeklySurveySet]:
    if not entry:
        return []
    raw_detail = entry.get("sets_detail")
    if isinstance(raw_detail, list) and raw_detail:
        sets: list[WeeklySurveySet] = []
        for item in raw_detail:
            try:
                sets.append(WeeklySurveySet.model_validate(item))
            except ValidationError:
                continue
        if sets:
            return sets
    sets_count = int(_parse_numeric_max(entry.get("sets"), fallback=1))
    reps_value = int(_parse_numeric_max(entry.get("reps"), fallback=1))
    weight_value = float(_parse_numeric_max(entry.get("weight"), fallback=0.0))
    sets_count = max(1, sets_count)
    reps_value = max(1, reps_value)
    weight_value = max(0.0, weight_value)
    return [WeeklySurveySet(reps=reps_value, weight=weight_value, weight_unit="kg") for _ in range(sets_count)]


def _normalize_sets_detail(
    exercise: WeeklySurveyExercise,
    *,
    fallback_entry: dict[str, Any] | None,
) -> list[WeeklySurveySet]:
    if exercise.sets_detail:
        return [
            WeeklySurveySet(reps=item.reps, weight=item.weight, weight_unit=item.weight_unit or "kg")
            for item in exercise.sets_detail
        ]
    return _extract_sets_from_entry(fallback_entry)


def build_progress_snapshot(
    payload: WeeklySurveyPayload,
    *,
    exercises_by_day: list[dict[str, Any]],
    week_start: date,
    resolve_entry: Callable[[list[dict[str, Any]], str], dict[str, Any] | None],
    plan_hash: str | None = None,
) -> ProgressSnapshotPayload:
    days_payload: list[ProgressDay] = []
    resolved_hash = plan_hash or compute_plan_hash(exercises_by_day)
    week_label = week_start.isoformat()
    for day in payload.days:
        exercises_payload: list[ProgressExercise] = []
        if not day.skipped:
            for exercise in day.exercises:
                entry = resolve_entry(exercises_by_day, exercise.id)
                sets = _normalize_sets_detail(exercise, fallback_entry=entry)
                sets_payload: list[ProgressSet] = [
                    {
                        "reps": int(item.reps),
                        "weight": float(item.weight),
                        "weight_unit": item.weight_unit or "kg",
                    }
                    for item in sets
                ]
                exercises_payload.append(
                    {
                        "id": exercise.id,
                        "name": exercise.name,
                        "difficulty": exercise.difficulty,
                        "comment": exercise.comment,
                        "sets": sets_payload,
                    }
                )
        days_payload.append(
            {
                "id": day.id,
                "title": day.title,
                "skipped": bool(day.skipped),
                "exercises": exercises_payload,
            }
        )
    return {"week_start": week_label, "plan_hash": resolved_hash, "days": days_payload}


def _format_progress_week(snapshot: ProgressSnapshotPayload) -> list[str]:
    days = snapshot.get("days") or []
    order: list[str] = []

    class _AggregateStats(TypedDict):
        reps: list[float]
        weights: list[float]
        difficulty: list[int]
        sets_count: int

    aggregates: dict[str, _AggregateStats] = {}
    for day in days:
        if day.get("skipped"):
            continue
        for exercise in day.get("exercises", []):
            name = str(exercise.get("name") or "").strip()
            if not name:
                continue
            if name not in aggregates:
                aggregates[name] = {
                    "reps": [],
                    "weights": [],
                    "difficulty": [],
                    "sets_count": 0,
                }
                order.append(name)
            stats = aggregates[name]
            stats["difficulty"].append(int(exercise.get("difficulty", 0)))
            sets = exercise.get("sets", [])
            if isinstance(sets, list):
                stats["sets_count"] += len(sets)
                for entry in sets:
                    stats["reps"].append(float(entry.get("reps", 0)))
                    stats["weights"].append(float(entry.get("weight", 0)))
    lines: list[str] = []
    for name in order:
        stats = aggregates[name]
        reps_values = [value for value in stats["reps"] if value > 0]
        weight_values = [value for value in stats["weights"] if value >= 0]
        reps_text = _format_range(reps_values) if reps_values else "n/a"
        weight_text = _format_range(weight_values) if weight_values else "n/a"
        difficulty_values = [value for value in stats["difficulty"] if value >= 0]
        difficulty_avg = round(sum(difficulty_values) / len(difficulty_values)) if difficulty_values else 0
        lines.append(
            f"- {name}: sets {stats['sets_count']}, reps {reps_text}, weight {weight_text} kg, "
            f"difficulty avg {difficulty_avg}"
        )
    if not lines:
        lines.append("- no exercises reported.")
    return lines


def build_progress_history_summary(
    snapshots: Sequence[ProgressSnapshotPayload],
    *,
    weeks: int,
) -> str | None:
    if not snapshots:
        return None
    sorted_snapshots = sorted(
        snapshots,
        key=lambda item: item.get("week_start") or "",
    )[-weeks:]
    lines: list[str] = []
    for snapshot in sorted_snapshots:
        week_label = snapshot.get("week_start") or "unknown"
        lines.append(f"Week starting {week_label}:")
        lines.extend(_format_progress_week(snapshot))
    return "\n".join(lines)


def resolve_plan_age_weeks_from_progress(
    snapshots: Sequence[ProgressSnapshotPayload],
    *,
    plan_hash: str | None,
) -> int | None:
    if not plan_hash or not snapshots:
        return None
    ordered = sorted(
        snapshots,
        key=lambda item: item.get("week_start") or "",
        reverse=True,
    )
    count = 0
    for snapshot in ordered:
        if snapshot.get("plan_hash") == plan_hash:
            count += 1
            continue
        break
    return count or None


def _difficulty_label(value: int) -> str:
    if value <= 33:
        return "easy"
    if value <= 66:
        return "moderate"
    return "hard"


def _format_range(values: list[float]) -> str:
    min_value = min(values)
    max_value = max(values)
    if min_value == max_value:
        return f"{min_value:g}"
    return f"{min_value:g}-{max_value:g}"


def _format_sets_detail(details: list[WeeklySurveySet] | None) -> str | None:
    if not details:
        return None
    reps_values = [float(item.reps) for item in details]
    weights = [float(item.weight) for item in details]
    reps_range = _format_range(reps_values)
    weight_unit = next((item.weight_unit for item in details if item.weight_unit), None)
    parts = [f"Sets: {len(details)} x {reps_range} reps"]
    if any(weight > 0 for weight in weights):
        weight_range = _format_range(weights)
        if weight_unit:
            parts.append(f"Weight: {weight_range} {weight_unit}")
        else:
            parts.append(f"Weight: {weight_range}")
    return ". ".join(parts)


def build_weekly_survey_feedback(
    payload: WeeklySurveyPayload,
    *,
    context: SurveyFeedbackContext,
    progress_history: str | None = None,
    progress_weeks: int | None = None,
) -> str:
    lines: list[str] = []
    if context.workout_goals:
        lines.append(f"Workout goals: {context.workout_goals}")
    if context.workout_experience:
        lines.append(f"Workout experience: {context.workout_experience}")
    if context.plan_age_weeks is not None:
        lines.append(f"Plan age: {context.plan_age_weeks} week(s) on current exercise list.")
    lines.append("Difficulty scale: 0 easiest, 50 moderate, 100 hardest.")
    lines.append("Weekly survey results:")
    for idx, day in enumerate(payload.days, start=1):
        day_title = day.title or f"Day {idx}"
        if day.skipped:
            lines.append(f"{day_title}: skipped.")
            continue
        if not day.exercises:
            lines.append(f"{day_title}: no exercises reported.")
            continue
        lines.append(f"{day_title}:")
        for exercise in day.exercises:
            label = _difficulty_label(exercise.difficulty)
            entry = f"- {exercise.name}: {exercise.difficulty}/100 ({label})"
            sets_text = _format_sets_detail(exercise.sets_detail)
            if sets_text:
                entry = f"{entry}. {sets_text}"
            if exercise.comment:
                entry = f"{entry}. Comment: {exercise.comment}"
            lines.append(entry)
    if progress_history:
        weeks_label = progress_weeks or 8
        lines.append(f"Progress history (last {weeks_label} weeks, weights in kg):")
        lines.append(progress_history)
    return "\n".join(lines)


def enqueue_subscription_update(
    *,
    profile_id: int,
    language: str,
    feedback: str,
    workout_location: WorkoutLocation | None,
    request_id: str,
) -> bool:
    try:
        payload_model = AiPlanUpdatePayload(
            profile_id=profile_id,
            language=language,
            plan_type=WorkoutPlanType.SUBSCRIPTION,
            feedback=feedback,
            workout_location=workout_location,
            request_id=request_id,
        )
    except ValidationError as exc:
        logger.error(
            f"weekly_survey_update_invalid_payload request_id={request_id} profile_id={profile_id} error={exc!s}"
        )
        return False

    payload = payload_model.model_dump(mode="json")
    headers = {
        "request_id": request_id,
        "profile_id": profile_id,
        "plan_type": WorkoutPlanType.SUBSCRIPTION.value,
    }
    options = {"queue": "ai_coach", "routing_key": "ai_coach", "headers": headers}

    try:
        if hasattr(update_ai_workout_plan, "s"):
            update_sig = update_ai_workout_plan.s(payload).set(**options)  # pyrefly: ignore[not-callable]
            notify_sig = notify_ai_plan_ready_task.s().set(  # pyrefly: ignore[not-callable]
                queue="ai_coach",
                routing_key="ai_coach",
                headers=headers,
            )
            failure_sig = handle_ai_plan_failure.s(payload, "update").set(  # pyrefly: ignore[not-callable]
                queue="ai_coach",
                routing_key="ai_coach",
            )
            async_result = chain(update_sig, notify_sig).apply_async(link_error=[failure_sig])
        else:
            async_result = update_ai_workout_plan.apply_async(  # pyrefly: ignore[not-callable]
                args=(payload,),
                queue="ai_coach",
                routing_key="ai_coach",
                headers=headers,
            )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"weekly_survey_update_dispatch_failed profile_id={profile_id} request_id={request_id} error={exc!s}"
        )
        return False

    task_id = getattr(async_result, "id", None)
    if task_id is None:
        logger.error(f"weekly_survey_update_missing_task_id request_id={request_id} profile_id={profile_id}")
        return False
    logger.info(
        "weekly_survey_update_enqueued request_id={} task_id={} profile_id={}",
        request_id,
        task_id,
        profile_id,
    )
    return True
