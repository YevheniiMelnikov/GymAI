import os

import aiohttp
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
            blob = self.bucket.blob(source_file_name)
            blob.upload_from_filename(f"temp/{source_file_name}")
            logger.info(f"File {source_file_name} successfully uploaded to GCS.")
            return True
        except Exception as e:
            logger.error(f"Failed to upload {source_file_name} to GCS: {e}")
            return False

    def generate_signed_url(self, file_name: str, expiration: int = 3600) -> str:
        blob = self.bucket.blob(file_name)
        url = blob.generate_signed_url(version="v4", expiration=expiration, method="GET")
        return url

    @staticmethod
    async def save_profile_photo(message: Message) -> str | None:
        file_id = message.photo[-1].file_id
        file = await message.bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file.file_path}"
        local_file_path = os.path.join("temp", f"{file_id}.jpg")
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as resp:
                if resp.status == 200:
                    with open(local_file_path, "wb") as f:
                        f.write(await resp.read())
                        logger.info(f"File {file_id} successfully saved locally")
                        return f"{file_id}.jpg"
                else:
                    logger.error(f"Error saving file {file_id}")
                    return None

    @staticmethod
    def clean_up_local_file(file: str) -> None:
        os.remove(f"temp/{file}")
        logger.info(f"File {file} successfully deleted")

    @staticmethod
    def check_file_size(file_path: str, max_size_mb: float) -> bool:
        file_size = os.path.getsize(file_path) / (1024 * 1024)
        return file_size <= max_size_mb


file_manager = FileManager(os.getenv("GCS_BUCKET"))
