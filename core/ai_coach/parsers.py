import json
import re
from pydantic import ValidationError

from core.schemas import DayExercises, Exercise
from .schemas import ProgramResponse, SubscriptionResponse


def parse_program_text(program_text: str) -> tuple[list[DayExercises], int]:
    """Parse plain text program into structured exercises."""
    days: list[DayExercises] = []
    if not program_text:
        return days, 0
    # Split by "Day X" headings
    pattern = re.compile(r"day\s*(\d+)[:.-]?", re.IGNORECASE)
    sections = pattern.split(program_text)
    iterator = iter(sections)
    next(iterator, None)  # discard text before first day
    for day_num, section in zip(iterator, iterator):
        exercises: list[Exercise] = []
        for line in section.splitlines():
            line = line.strip("- ")
            if not line:
                continue
            exercises.append(Exercise(name=line, sets="", reps=""))
        days.append(DayExercises(day=f"day_{day_num}", exercises=exercises))
    return days, len(days)


def parse_program_json(program_json: str) -> ProgramResponse | None:
    """Validate and deserialize JSON program returned by the LLM."""
    try:
        data = json.loads(program_json)
        return ProgramResponse.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        return None


def parse_subscription_json(subscription_json: str) -> SubscriptionResponse | None:
    """Validate and deserialize JSON subscription plan returned by the LLM."""
    try:
        data = json.loads(subscription_json)
        return SubscriptionResponse.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        return None
