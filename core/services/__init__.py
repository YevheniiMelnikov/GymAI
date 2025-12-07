from functools import lru_cache

from config.app_settings import settings
from core.services.gstorage_service import ExerciseGIFStorage
from core.services.internal import APIService
from core.services.internal.profile_service import ProfileService
from core.services.internal.workout_service import WorkoutService

BUCKET_EXERCISES_GUIDE = settings.EXERCISE_GIF_BUCKET


@lru_cache(maxsize=1)
def get_gif_manager() -> ExerciseGIFStorage:
    return ExerciseGIFStorage(BUCKET_EXERCISES_GUIDE)


__all__ = [
    "get_gif_manager",
    "APIService",
    "ProfileService",
    "WorkoutService",
]
