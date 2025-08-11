from __future__ import annotations

import json
import re
from typing import Any, cast
from pydantic import ValidationError

from core.schemas import DayExercises, Exercise
from .schemas import ProgramResponse, SubscriptionResponse


def parse_program_text(program_text: str) -> tuple[list[DayExercises], int]:
    """Parse plain text program into structured exercises."""
    days: list[DayExercises] = []
    if not program_text:
        return days, 0
    pattern = re.compile(r"day\s*(\d+)[:.-]?", re.IGNORECASE)
    sections = pattern.split(program_text)
    iterator = iter(sections)
    next(iterator, None)
    for day_num, section in zip(iterator, iterator):
        exercises: list[Exercise] = []
        for line in section.splitlines():
            line = line.strip("- ")
            if not line:
                continue
            exercises.append(Exercise(name=line, sets="", reps=""))
        try:
            day_index = str(int(day_num) - 1)
        except ValueError:
            day_index = day_num
        days.append(DayExercises(day=day_index, exercises=exercises))
    return days, len(days)


def extract_json(text: str) -> str | None:
    """Return the first JSON object found within ``text``."""
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        return match.group(0)
    return None


def normalize_program_data(data: dict[str, Any], *, key: str = "days") -> None:
    """Normalize day identifiers and exercise fields in program JSON."""
    for day_raw in data.get(key, []):
        day = cast(dict[str, Any], day_raw)
        day_val = str(day.get("day", ""))
        match = re.search(r"\d+", day_val)
        if match:
            day_num = int(match.group(0))
            day["day"] = str(day_num - 1)
        for ex_raw in day.get("exercises", []):
            ex = cast(dict[str, Any], ex_raw)
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
    extracted = extract_json(program_json)
    if extracted:
        program_json = extracted
    try:
        data = json.loads(program_json)
        normalize_program_data(data, key="days")
        if "days" in data:
            data["days"] = sorted(data["days"], key=lambda d: int(d.get("day", 0)))
        return ProgramResponse.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        return None


def parse_subscription_json(subscription_json: str) -> SubscriptionResponse | None:
    """Validate and deserialize JSON subscription plan returned by the LLM."""
    if not subscription_json:
        return None
    extracted = extract_json(subscription_json)
    if extracted:
        subscription_json = extracted
    try:
        data = json.loads(subscription_json)
        normalize_program_data(data, key="exercises")
        if "exercises" in data:
            data["exercises"] = sorted(data["exercises"], key=lambda d: d.get("day", ""))
        return SubscriptionResponse.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        return None
