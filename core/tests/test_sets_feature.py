
from bot.utils.exercises import create_exercise, format_program
from core.schemas import DayExercises, Exercise
import asyncio


class DummyState:
    def __init__(self):
        self.data = {}

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def get_data(self):
        return self.data


def test_create_exercise_with_set():
    async def runner():
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
            False,
        )
        assert exercise.set_id == 1
        assert exercises[0].exercises[0].set_id == 1

    asyncio.run(runner())


def test_format_program_with_set():
    async def runner():
        exercises = [
            DayExercises(
                day="0",
                exercises=[
                    Exercise(name="Push", sets="3", reps="10", set_id=1),
                    Exercise(name="Pull", sets="3", reps="10", set_id=1),
                ],
            )
        ]
        formatted = await format_program(exercises, 0)
        assert "Set 1" in formatted

    asyncio.run(runner())


def test_create_exercise_with_dropset():
    async def runner():
        state = DummyState()
        await state.update_data(day_index=0)
        exercises: list[DayExercises] = []
        exercise = await create_exercise(
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
        assert exercise.drop_set is True
        assert exercises[0].exercises[0].drop_set is True
        formatted = await format_program(exercises, 0)
        assert "Drop set" in formatted

    asyncio.run(runner())
