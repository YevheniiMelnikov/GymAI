import os

from loguru import logger
from aiogram.types import Message
from google.cloud import storage


class GCStorageService:
    def __init__(self, bucket_name: str):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)

    def load_file_to_bucket(self, source_file_name: str) -> bool:
        try:
            blob = self.bucket.blob(os.path.basename(source_file_name))
            blob.upload_from_filename(source_file_name)
            logger.debug(f"File {source_file_name[:10]}...jpg successfully uploaded to storage")
            return True
        except Exception as e:
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
    def check_file_size(file_path: str, max_size_mb: float) -> bool:
        file_size = os.path.getsize(file_path) / (1024 * 1024)
        return file_size <= max_size_mb


avatar_manager = GCStorageService("coach_avatars")
gif_manager = GCStorageService("exercises_guide")
