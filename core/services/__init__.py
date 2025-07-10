from core.services.gdrive_loader import GDriveDocumentLoader
from core.services.gstorage_service import GCStorageService, ExerciseGIFStorage

avatar_manager = GCStorageService("coach_avatars")
gif_manager = ExerciseGIFStorage("exercises_guide")

__all__ = [
    "avatar_manager",
    "gif_manager",
    "GDriveDocumentLoader",
]
