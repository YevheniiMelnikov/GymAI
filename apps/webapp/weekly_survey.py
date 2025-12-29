from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from celery import chain
from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator

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
    weight_unit: str | None = None


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
