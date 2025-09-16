from apps.webapp.utils import _format_full_program, normalize_day_exercises
from core.schemas import DayExercises, Exercise


def test_normalize_day_exercises_respects_textual_labels() -> None:
    raw = {
        "День 2 — Legs": ["exercise"],
        "День 1 — Chest": ["exercise"],
    }

    normalized = normalize_day_exercises(raw)

    assert [item["day"] for item in normalized] == [
        "День 1 — Chest",
        "День 2 — Legs",
    ]


def test_format_full_program_handles_mixed_day_labels() -> None:
    exercises = [
        DayExercises(
            day="День 2 — Legs",
            exercises=[Exercise(name="Squat", sets="4", reps="8", weight="60 kg")],
        ),
        DayExercises(
            day="0",
            exercises=[Exercise(name="Push-up", sets="3", reps="12")],
        ),
    ]

    rendered = _format_full_program(exercises)

    assert rendered.splitlines() == [
        "Day 1",
        "1. Push-up | 3 x 12",
        "",
        "День 2 — Legs",
        "1. Squat | 4 x 8 | 60 kg",
    ]
