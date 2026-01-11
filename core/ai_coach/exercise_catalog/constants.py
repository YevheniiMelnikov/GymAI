EXERCISE_CATEGORIES: set[str] = {"conditioning", "strength", "health"}
EQUIPMENT_TYPES: set[str] = {
    "kettlebell",
    "dumbbell",
    "barbell",
    "smith",
    "lever",
    "cable",
    "band",
    "bodyweight",
    "weighted bodyweight",
}
MUSCLE_GROUPS: set[str] = {
    "chest",
    "upper_back",
    "lats",
    "lower_back",
    "front_delts",
    "side_delts",
    "rear_delts",
    "biceps",
    "triceps",
    "forearms",
    "quadriceps",
    "hamstrings",
    "glutes",
    "calves",
    "adductors",
    "abductors",
    "abs",
    "obliques",
    "core",
}

__all__ = ["EQUIPMENT_TYPES", "EXERCISE_CATEGORIES", "MUSCLE_GROUPS"]
