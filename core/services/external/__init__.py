from core.services.external.gstorage_service import GCStorageService, ExerciseGIFStorage
from core.services.external.gdrive_loader import GDriveDocumentLoader

avatar_manager = GCStorageService("coach_avatars")
gif_manager = ExerciseGIFStorage("exercises_guide")

__all__ = [
    "avatar_manager",
    "gif_manager",
    "GDriveDocumentLoader",
]
