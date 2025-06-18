import pytest

from bot.utils.exercises import create_exercise, format_program
from core.schemas import DayExercises, Exercise

class DummyState:
    def __init__(self):
        self.data = {}
    async def update_data(self, **kwargs):
        self.data.update(kwargs)
    async def get_data(self):
        return self.data

@pytest.mark.asyncio
async def test_create_exercise_with_set():
    state = DummyState()
    await state.update_data(day_index=0, set_id=1)
    exercises: list[DayExercises] = []
    exercise = await create_exercise(
        {
            "exercise_name": "Push Up",
            "sets": "3",
            "reps": "10",
            "set_id": 1,
        },
        exercises,
        state,
        None,
    )
    assert exercise.set_id == 1
    assert exercises[0].exercises[0].set_id == 1

@pytest.mark.asyncio
async def test_format_program_with_set():
    exercises = [
        DayExercises(day="0", exercises=[
            Exercise(name="Push", sets="3", reps="10", set_id=1),
            Exercise(name="Pull", sets="3", reps="10", set_id=1),
        ])
    ]
    formatted = await format_program(exercises, 0)
    assert "Set 1" in formatted
