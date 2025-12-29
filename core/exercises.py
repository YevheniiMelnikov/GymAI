from typing import Any

from loguru import logger

from core.schemas import DayExercises


def serialize_day_exercises(exercises: list[DayExercises]) -> list[dict[str, Any]]:
    """Serialize a list of DayExercises into plain dictionaries."""
    result: list[dict[str, Any]] = []
    for day in exercises:
        day_obj = day
        if not isinstance(day_obj, DayExercises):
            try:
                day_obj = DayExercises.model_validate(day)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"skip_invalid_day_exercises err={exc}")
                continue
        result.append(
            {
                "day": day_obj.day,
                "exercises": [exercise.model_dump() for exercise in day_obj.exercises],
            }
        )
    return result
