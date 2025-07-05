import os

from loguru import logger
from aiogram.types import Message
from google.cloud import storage
from google.auth.exceptions import DefaultCredentialsError

from config.env_settings import settings
from core.cache import Cache


class GCStorageService:
    def __init__(self, bucket_name: str):
        self.bucket_name = bucket_name
        try:
            self.storage_client = storage.Client()
            self.bucket = self.storage_client.bucket(bucket_name)
        except DefaultCredentialsError as exc:  # noqa: BLE001
            logger.error(f"GCS credentials error: {exc}")
            self.storage_client = None  # pyre-ignore[bad-assignment]
            self.bucket = None  # pyre-ignore[bad-assignment]

    def load_file_to_bucket(self, source_file_name: str) -> bool:
        if not self.bucket:
            logger.warning("GCS bucket is not configured")
            return False
        try:
            blob = self.bucket.blob(os.path.basename(source_file_name))
            blob.upload_from_filename(source_file_name)
            logger.debug(f"File {source_file_name[:10]}...jpg successfully uploaded to storage")
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to upload {source_file_name[:10]}...jpg to storage: {e}")
            return False

    @staticmethod
    async def save_image(message: Message) -> str | None:
        try:
            if not message.photo:
                return None
            photo = message.photo[-1]
            file_id = photo.file_id

            bot = message.bot
            if bot is None:
                return None

            file = await bot.get_file(file_id)
            if file.file_path is None:
                return None

            local_file_path = f"{file_id}.jpg"
            await bot.download_file(file.file_path, destination=local_file_path)

            logger.debug(f"File {file_id[:10]}...jpg successfully saved locally")
            await message.delete()
            return local_file_path

        except Exception as e:
            logger.error(f"Error saving file: {e}")
            return None

    @staticmethod
    def clean_up_file(file: str) -> None:
        if os.path.exists(file):
            os.remove(file)
            logger.debug(f"File {file[:10]}...jpg successfully deleted")
        else:
            logger.warning(f"File {file[:10]}...jpg does not exist, skipping deletion")

    @staticmethod
    def check_file_size(file_path: str) -> bool:
        file_size = os.path.getsize(file_path) / (1024 * 1024)
        return file_size <= settings.MAX_FILE_SIZE_MB


class ExerciseGIFStorage(GCStorageService):
    async def find_gif(self, exercise: str, exercise_dict: dict[str, list[str]]) -> str | None:
        if not self.bucket:
            logger.warning("GCS bucket is not configured")
            return None
        try:
            exercise_lc = exercise.lower()
            for filename, synonyms in exercise_dict.items():
                if exercise_lc in (syn.lower() for syn in synonyms):
                    cached = await Cache.workout.get_exercise_gif(exercise_lc)
                    if cached:
                        return f"https://storage.googleapis.com/{self.bucket_name}/{cached}"

                    blobs = list(self.bucket.list_blobs(prefix=filename))
                    if blobs:
                        blob = blobs[0]
                        if blob.exists():
                            file_url = f"https://storage.googleapis.com/{self.bucket_name}/{blob.name}"
                            for syn in synonyms:
                                await Cache.workout.cache_gif_filename(syn.lower(), blob.name)
                            return file_url
        except Exception as e:
            logger.error(f"Failed to find gif for exercise {exercise}: {e}")

        logger.debug(f"No matching file found for exercise: {exercise}")
        return None
