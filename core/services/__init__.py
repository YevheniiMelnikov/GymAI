from functools import lru_cache
from typing import Final

from core.services.gstorage_service import GCStorageService, ExerciseGIFStorage
from core.services.internal import APIService
from core.services.internal.profile_service import ProfileService
from core.services.internal.workout_service import WorkoutService

BUCKET_COACH_AVATARS: Final[str] = "coach_avatars"
BUCKET_EXERCISES_GUIDE: Final[str] = "exercises_guide"


@lru_cache(maxsize=1)
def get_avatar_manager() -> GCStorageService:
    return GCStorageService(BUCKET_COACH_AVATARS)


@lru_cache(maxsize=1)
def get_gif_manager() -> ExerciseGIFStorage:
    return ExerciseGIFStorage(BUCKET_EXERCISES_GUIDE)


__all__ = [
    "get_avatar_manager",
    "get_gif_manager",
    "APIService",
    "ProfileService",
    "WorkoutService",
]
