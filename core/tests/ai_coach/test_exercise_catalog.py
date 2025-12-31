from core.ai_coach.exercise_catalog import ExerciseCatalogEntry, filter_exercise_entries


def test_filter_exercise_entries_by_category_muscles_and_name() -> None:
    entries = [
        ExerciseCatalogEntry(
            gif_key="pullover.gif",
            canonical="Barbell Pullover",
            aliases=("Bench Barbell Pullover",),
            category="strength",
            primary_muscles=("lats",),
            secondary_muscles=("chest",),
        ),
        ExerciseCatalogEntry(
            gif_key="jump.gif",
            canonical="Jump Rope",
            aliases=("Skipping Rope",),
            category="conditioning",
            primary_muscles=("calves",),
            secondary_muscles=("core",),
        ),
    ]

    results = filter_exercise_entries(
        entries,
        category="strength",
        primary_muscles=["lats"],
        name_query="pullover",
    )

    assert [item.gif_key for item in results] == ["pullover.gif"]
