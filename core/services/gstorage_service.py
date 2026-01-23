import os
from datetime import timedelta
from pathlib import Path
from typing import cast

from loguru import logger
from google.cloud import storage
from google.auth.exceptions import DefaultCredentialsError

from config.app_settings import settings


class ExerciseGIFStorage:
    """Resolve exercise GIF URLs with optional signed links."""

    def __init__(self, bucket_name: str) -> None:
        self.bucket_name = bucket_name
        self._warned_missing_client = False
        creds_path = Path(settings.GOOGLE_APPLICATION_CREDENTIALS)
        self.storage_client: storage.Client | None = None
        self.bucket: storage.bucket.Bucket | None = None
        try:
            if creds_path.exists():
                self.storage_client = cast(
                    storage.Client,
                    storage.Client.from_service_account_json(str(creds_path)),
                )
            else:
                logger.warning("GCS credentials file not found path={}", creds_path)
                self.storage_client = storage.Client()
            if self.storage_client is not None:
                self.bucket = self.storage_client.bucket(bucket_name)
                credentials = getattr(self.storage_client, "_credentials", None)
            else:
                credentials = None
            service_account = getattr(credentials, "service_account_email", None)
            project_id = getattr(self.storage_client, "project", None)
            if service_account:
                logger.info(
                    "GCS client ready bucket={} account={} project={}",
                    bucket_name,
                    service_account,
                    project_id,
                )
        except DefaultCredentialsError as exc:  # noqa: BLE001
            creds_hint = "set" if os.getenv("GOOGLE_APPLICATION_CREDENTIALS") else "missing"
            logger.error(f"GCS credentials error: {exc} google_credentials={creds_hint}")
        self.base_url = settings.EXERCISE_GIF_BASE_URL.rstrip("/")

    def find_gif(self, gif_name: str) -> str | None:
        safe_name = str(gif_name or "").strip().lstrip("/")
        if not safe_name:
            return None

        ttl_seconds = int(getattr(settings, "EXERCISE_GIF_URL_TTL_SEC", 0) or 0)
        if ttl_seconds > 0 and self.bucket is not None:
            try:
                blob = self.bucket.blob(safe_name)
                signed_url = blob.generate_signed_url(
                    expiration=timedelta(seconds=ttl_seconds),
                    version="v4",
                )
                return signed_url
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Failed to sign GIF url gif_name={safe_name} error={exc}")
        if self.bucket is None and not self._warned_missing_client:
            logger.warning("GCS client unavailable; using public GIF URLs without signing")
            self._warned_missing_client = True
        return f"{self.base_url}/{self.bucket_name}/{safe_name}"
