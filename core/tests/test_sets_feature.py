import pytest
from dataclasses import dataclass


@dataclass
class Exercise:
    name: str
    sets: str
    reps: str
    set_id: int | None = None
    drop_set: bool = False


@dataclass
class DayExercises:
    day: str
    exercises: list[Exercise]


async def create_exercise(data, exercises, state, _msg, drop_set: bool):
    day_index = state.data.get("day_index", 0)
    exercise = Exercise(
        name=data["exercise_name"],
        sets=data["sets"],
        reps=data["reps"],
        set_id=data.get("set_id"),
        drop_set=drop_set,
    )
    if not exercises:
        exercises.append(DayExercises(day=str(day_index), exercises=[]))
    exercises[0].exercises.append(exercise)
    return exercise


async def format_program(exercises, day_index: int) -> str:
    day = exercises[day_index]
    lines = []
    current_set = None
    for ex in day.exercises:
        if ex.set_id and ex.set_id != current_set:
            current_set = ex.set_id
            lines.append(f"Set {current_set}")
        line = f"{ex.name}: {ex.sets}x{ex.reps}"
        if ex.drop_set:
            line += " Drop set"
        lines.append(line)
    return "\n".join(lines)


class DummyState:
    def __init__(self):
        self.data = {}

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def get_data(self):
        return self.data


def test_create_exercise_with_set():
    import asyncio

    state = DummyState()
    asyncio.run(state.update_data(day_index=0, set_id=1))
    exercises: list[DayExercises] = []
    exercise = asyncio.run(
        create_exercise(
            {
                "exercise_name": "Push Up",
                "sets": "3",
                "reps": "10",
                "set_id": 1,
            },
            exercises,
            state,
            None,
            False,
        )
    )
    assert exercise.set_id == 1
    assert exercises[0].exercises[0].set_id == 1


def test_format_program_with_set():
    import asyncio

    exercises = [
        DayExercises(
            day="0",
            exercises=[
                Exercise(name="Push", sets="3", reps="10", set_id=1),
                Exercise(name="Pull", sets="3", reps="10", set_id=1),
            ],
        )
    ]
    formatted = asyncio.run(format_program(exercises, 0))
    assert "Set 1" in formatted


def test_create_exercise_with_dropset():
    import asyncio

    state = DummyState()
    asyncio.run(state.update_data(day_index=0))
    exercises: list[DayExercises] = []
    exercise = asyncio.run(
        create_exercise(
            {
                "exercise_name": "Push",
                "sets": "3",
                "reps": "10",
            },
            exercises,
            state,
            None,
            True,
        )
    )
    assert exercise.drop_set is True
    assert exercises[0].exercises[0].drop_set is True
    formatted = asyncio.run(format_program(exercises, 0))
    assert "Drop set" in formatted
