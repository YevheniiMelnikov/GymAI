from ai_coach.agent.utils import apply_workout_aux_rules, ensure_catalog_gif_keys, fill_missing_gif_keys


def test_aux_rules_insert_warmup_first_and_skip_gif_resolution() -> None:
    exercises_by_day = [{"day": "day1", "exercises": [{"name": "Squat", "sets": "3", "reps": "10"}]}]

    apply_workout_aux_rules(
        exercises_by_day,
        language="ru",
        workout_location="gym",
        wishes="",
        prompt="",
        profile_context="",
    )

    first = exercises_by_day[0]["exercises"][0]
    assert first["kind"] == "warmup"
    assert "Разминка" in first["name"]
    assert first.get("gif_key") is None

    fill_missing_gif_keys(exercises_by_day)
    ensure_catalog_gif_keys(exercises_by_day)
    assert exercises_by_day[0]["exercises"][0].get("gif_key") is None


def test_aux_rules_moves_cardio_to_end_as_text_block() -> None:
    exercises_by_day = [
        {
            "day": "day1",
            "exercises": [
                {"name": "Squat", "sets": "3", "reps": "10"},
                {"name": "Бег 15 минут", "sets": "1", "reps": "15 min"},
            ],
        }
    ]

    apply_workout_aux_rules(
        exercises_by_day,
        language="ru",
        workout_location="gym",
        wishes="",
        prompt="",
        profile_context="",
    )

    exercises = exercises_by_day[0]["exercises"]
    assert exercises[0]["kind"] == "warmup"
    assert exercises[-1]["kind"] == "cardio"
    assert "Кардио" in exercises[-1]["name"]
