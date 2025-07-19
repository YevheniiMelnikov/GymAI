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


def _extract_json(text: str) -> str | None:
    """Return the first JSON object found within ``text``."""
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        return match.group(0)
    return None


def _normalize_program_data(data: dict, *, key: str = "days") -> None:
    """Normalize day identifiers and exercise fields in program JSON."""
    for day in data.get(key, []):
        day_val = str(day.get("day", ""))
        match = re.search(r"\d+", day_val)
        if match:
            day_num = int(match.group(0))
            day["day"] = str(day_num - 1)
        for ex in day.get("exercises", []):
            sets = ex.get("sets")
            ex["sets"] = str(sets) if sets is not None else ""
            reps = ex.get("reps")
            if reps is None:
                time_val = ex.pop("time", None)
                ex["reps"] = str(time_val) if time_val is not None else ""
            else:
                ex["reps"] = str(reps)
            weight = ex.get("weight")
            if weight is not None:
                ex["weight"] = str(weight)


def parse_program_json(program_json: str) -> ProgramResponse | None:
    """Validate and deserialize JSON program returned by the LLM."""
    if not program_json:
        return None
    extracted = _extract_json(program_json)
    if extracted:
        program_json = extracted
    try:
        data = json.loads(program_json)
        _normalize_program_data(data, key="days")
        return ProgramResponse.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        return None


def parse_subscription_json(subscription_json: str) -> SubscriptionResponse | None:
    """Validate and deserialize JSON subscription plan returned by the LLM."""
    if not subscription_json:
        return None
    extracted = _extract_json(subscription_json)
    if extracted:
        subscription_json = extracted
    try:
        data = json.loads(subscription_json)
        _normalize_program_data(data, key="exercises")
        return SubscriptionResponse.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        return None
