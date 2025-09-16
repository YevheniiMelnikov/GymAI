import pytest

from core.schemas import DayExercises, Exercise, Program


@pytest.mark.parametrize(
    "split_number,expected",
    [
        (None, 1),
        (2, 2),
    ],
)
def test_program_split_number_default(split_number: int | None, expected: int) -> None:
    exercises: list[DayExercises] = [DayExercises(day="0", exercises=[Exercise(name="Test", sets="3", reps="10")])]
    data: dict[str, object] = {
        "id": 1,
        "client_profile": 1,
        "exercises_by_day": [ex.model_dump() for ex in exercises],
        "created_at": 0,
    }
    if split_number is not None:
        data["split_number"] = split_number
    program = Program.model_validate(data)
    assert program.split_number == expected
