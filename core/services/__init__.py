from core.services.gdrive_loader import GDriveDocumentLoader
from core.services.gstorage_service import GCStorageService, ExerciseGIFStorage
from core.services.internal import APIService
from core.services.internal.profile_service import ProfileService
from core.services.internal.workout_service import WorkoutService
from core.services.payments.liqpay import LiqPayGateway, ParamValidationError

avatar_manager = GCStorageService("coach_avatars")
gif_manager = ExerciseGIFStorage("exercises_guide")

__all__ = [
    "avatar_manager",
    "gif_manager",
    "GDriveDocumentLoader",
    "APIService",
    "ProfileService",
    "WorkoutService",
    "LiqPayGateway",
    "ParamValidationError",
]
