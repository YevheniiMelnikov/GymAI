import os

import loguru
from aiogram.types import Message
from google.cloud import storage

logger = loguru.logger


class FileManager:
    def __init__(self, bucket_name: str):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)

    def upload_image_to_gcs(self, source_file_name: str) -> bool:
        try:
            blob = self.bucket.blob(os.path.basename(source_file_name))
            blob.upload_from_filename(source_file_name)
            logger.debug(f"File {source_file_name[:10]}...jpg successfully uploaded to storage")
            return True
        except Exception as e:
            logger.error(f"Failed to upload {source_file_name[:10]}...jpg to storage: {e}")
            return False

    @staticmethod
    async def save_profile_photo(message: Message) -> str | None:
        try:
            photo = message.photo[-1]
            file_id = photo.file_id
            file = await message.bot.get_file(file_id)
            local_file_path = f"{file_id}.jpg"
            await message.bot.download_file(file.file_path, destination=local_file_path)
            logger.debug(f"File {file_id[:10]}...jpg successfully saved locally")
            await message.delete()
            return local_file_path

        except Exception as e:
            logger.error(f"Error saving file: {e}")
            return None

    @staticmethod
    def clean_up_local_file(file: str) -> None:
        if os.path.exists(file):
            os.remove(file)
            logger.debug(f"File {file[:10]}...jpg successfully deleted")
        else:
            logger.warning(f"File {file[:10]}...jpg does not exist, skipping deletion")

    @staticmethod
    def check_file_size(file_path: str, max_size_mb: float) -> bool:
        file_size = os.path.getsize(file_path) / (1024 * 1024)
        return file_size <= max_size_mb


avatar_manager = FileManager("coach_avatars")
gif_manager = FileManager("exercises_guide")
