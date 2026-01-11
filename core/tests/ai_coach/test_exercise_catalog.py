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
            equipment=("barbell",),
        ),
        ExerciseCatalogEntry(
            gif_key="jump.gif",
            canonical="Jump Rope",
            aliases=("Skipping Rope",),
            category="conditioning",
            primary_muscles=("calves",),
            secondary_muscles=("core",),
            equipment=("bodyweight",),
        ),
    ]

    results = filter_exercise_entries(
        entries,
        category="strength",
        primary_muscles=["lats"],
        name_query="pullover",
    )

    assert [item.gif_key for item in results] == ["pullover.gif"]


def test_filter_exercise_entries_by_equipment() -> None:
    entries = [
        ExerciseCatalogEntry(
            gif_key="band-row.gif",
            canonical="Band Row",
            aliases=(),
            category="strength",
            primary_muscles=("upper_back",),
            secondary_muscles=("biceps",),
            equipment=("band", "bodyweight"),
        ),
        ExerciseCatalogEntry(
            gif_key="barbell-row.gif",
            canonical="Barbell Row",
            aliases=(),
            category="strength",
            primary_muscles=("upper_back",),
            secondary_muscles=("biceps",),
            equipment=("barbell",),
        ),
    ]

    results = filter_exercise_entries(entries, equipment=["band", "bodyweight"])

    assert [item.gif_key for item in results] == ["band-row.gif"]


def test_filter_exercise_entries_returns_all_when_limit_is_none() -> None:
    entries = [
        ExerciseCatalogEntry(
            gif_key="press-1.gif",
            canonical="Barbell Press",
            aliases=(),
            category="strength",
            primary_muscles=("chest",),
            secondary_muscles=("triceps",),
            equipment=("barbell",),
        ),
        ExerciseCatalogEntry(
            gif_key="press-2.gif",
            canonical="Barbell Bench Press",
            aliases=(),
            category="strength",
            primary_muscles=("chest",),
            secondary_muscles=("triceps",),
            equipment=("barbell",),
        ),
        ExerciseCatalogEntry(
            gif_key="press-3.gif",
            canonical="Incline Barbell Press",
            aliases=(),
            category="strength",
            primary_muscles=("chest",),
            secondary_muscles=("triceps",),
            equipment=("barbell",),
        ),
    ]

    results = filter_exercise_entries(entries, equipment=["barbell"], limit=None)

    assert [item.gif_key for item in results] == ["press-1.gif", "press-2.gif", "press-3.gif"]
