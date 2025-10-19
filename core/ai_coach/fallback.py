from __future__ import annotations

from datetime import datetime, timezone
from time import time
from typing import Sequence

from core.enums import CoachType, WorkoutPlanType
from core.schemas import DayExercises, Exercise, Program, Subscription

FALLBACK_WORKOUT_DAYS: tuple[str, ...] = ("Пн", "Ср", "Пт", "Сб")

_ROUTINE: tuple[tuple[tuple[str, str, str], ...], ...] = (
    (
        ("Warm-up cardio", "1", "8-10 min"),
        ("Barbell back squat", "4", "6-10"),
        ("Romanian deadlift", "3", "10-12"),
        ("Plank", "3", "45 sec"),
    ),
    (
        ("Warm-up mobility", "1", "8-10 min"),
        ("Bench press", "4", "6-10"),
        ("Bent-over row", "3", "8-12"),
        ("Dumbbell shoulder press", "3", "10-12"),
    ),
    (
        ("Warm-up bike", "1", "10 min"),
        ("Deadlift", "4", "5-8"),
        ("Walking lunges", "3", "12 per leg"),
        ("Hanging leg raises", "3", "12-15"),
    ),
    (
        ("Warm-up jump rope", "1", "5 min"),
        ("Pull-ups or lat pull-down", "4", "8-12"),
        ("Push-ups", "3", "15-20"),
        ("Farmer carry", "3", "40 m"),
    ),
)


def _ensure_days(workout_days: Sequence[str] | None) -> list[str]:
    days = [day for day in (workout_days or []) if day]
    return days or list(FALLBACK_WORKOUT_DAYS)


def _build_day(day_name: str, template: tuple[tuple[str, str, str], ...], base_index: int) -> DayExercises:
    exercises = [
        Exercise(
            name=name,
            sets=sets,
            reps=reps,
            set_id=100_000 + base_index * 10 + offset,
        )
        for offset, (name, sets, reps) in enumerate(template)
    ]
    return DayExercises(day=day_name, exercises=exercises)


def _build_days(workout_days: Sequence[str] | None) -> list[DayExercises]:
    days = _ensure_days(workout_days)
    routine_length = len(_ROUTINE)
    return [_build_day(day_name, _ROUTINE[index % routine_length], index) for index, day_name in enumerate(days)]


def fallback_plan(
    *,
    plan_type: WorkoutPlanType | None,
    client_profile_id: int,
    workout_type: str | None,
    wishes: str | None,
    workout_days: Sequence[str] | None,
    period: str | None = None,
) -> Program | Subscription:
    resolved_plan_type = plan_type or WorkoutPlanType.PROGRAM
    normalized_days = _ensure_days(workout_days)
    exercises = _build_days(normalized_days)
    normalized_workout_type = workout_type or "general"
    normalized_wishes = wishes or ""

    if resolved_plan_type is WorkoutPlanType.PROGRAM:
        return Program(
            id=0,
            client_profile=client_profile_id,
            exercises_by_day=exercises,
            created_at=time(),
            split_number=len(exercises),
            workout_type=normalized_workout_type,
            wishes=normalized_wishes,
            coach_type=CoachType.ai_coach,
        )

    payment_date = datetime.now(timezone.utc).date().isoformat()
    return Subscription(
        id=0,
        client_profile=client_profile_id,
        enabled=True,
        price=0,
        workout_type=normalized_workout_type,
        wishes=normalized_wishes,
        period=period or "one_month",
        workout_days=list(normalized_days),
        exercises=exercises,
        payment_date=payment_date,
    )


__all__ = ["fallback_plan", "FALLBACK_WORKOUT_DAYS"]
