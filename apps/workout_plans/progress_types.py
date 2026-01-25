from typing import TypedDict


class ProgressSet(TypedDict):
    reps: int
    weight: float
    weight_unit: str


class ProgressExercise(TypedDict):
    id: str
    name: str
    difficulty: int
    comment: str | None
    sets: list[ProgressSet]


class ProgressDay(TypedDict):
    id: str
    title: str | None
    skipped: bool
    exercises: list[ProgressExercise]


class ProgressSnapshotPayload(TypedDict):
    week_start: str
    plan_hash: str | None
    days: list[ProgressDay]
