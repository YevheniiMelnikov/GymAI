from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from loguru import logger
from docx import Document
import fitz
import cognee

from config.env_settings import settings
from core.services.ai.knowledge_loader import KnowledgeLoader


SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
ALLOWED_EXTS = {".pdf", ".docx", ".txt"}


class GDriveDocumentLoader(KnowledgeLoader):
    """Load documents from Google Drive into Cognee."""

    def __init__(self, folder_id: str) -> None:
        self.folder_id = folder_id
        self.credentials_path = settings.GOOGLE_APPLICATION_CREDENTIALS
        self._files_service: Any | None = None

    def _get_drive_service(self) -> Any:
        creds = Credentials.from_service_account_file(self.credentials_path, scopes=SCOPES)
        service = build("drive", "v3", credentials=creds)
        return service.files()

    async def _download_file(self, file_id: str) -> bytes:
        files_service = self._files_service

        def _do_download() -> bytes:
            assert files_service is not None
            request = files_service.get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return fh.getvalue()

        return await asyncio.to_thread(_do_download)

    @staticmethod
    def _parse_pdf(data: bytes) -> str:
        with fitz.open(stream=data, filetype="pdf") as doc:
            return "\n".join(page.get_text() for page in doc)

    @staticmethod
    def _parse_docx(data: bytes) -> str:
        document = Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs)

    @staticmethod
    def _parse_txt(data: bytes) -> str:
        return data.decode("utf-8", errors="ignore")

    async def load(self) -> None:
        self._files_service = self._get_drive_service()
        page_token: str | None = None

        while True:
            response = await asyncio.to_thread(
                lambda: self._files_service.list(
                    q=f"'{self.folder_id}' in parents and trashed=false",
                    fields="nextPageToken, files(id, name, mimeType, size)",
                    pageToken=page_token,
                ).execute()
            )
            for file in response.get("files", []):
                name = file.get("name", "")
                file_id = file.get("id")
                size = int(file.get("size", 0))
                ext = Path(name).suffix.lower()

                if ext not in ALLOWED_EXTS:
                    continue
                if size > settings.MAX_FILE_SIZE_MB:
                    logger.info(f"Skip {name}: file too large")
                    continue
                if not file_id:
                    continue

                try:
                    data = await self._download_file(file_id)
                    if ext == ".pdf":
                        text = await asyncio.to_thread(self._parse_pdf, data)
                    elif ext == ".docx":
                        text = await asyncio.to_thread(self._parse_docx, data)
                    else:
                        text = self._parse_txt(data)

                    if not text.strip():
                        continue

                    await cognee.add(text, dataset_name="external_docs", node_set=[f"gdrive:{name}"])
                except Exception as exc:
                    logger.error(f"Failed to process {name}: {exc}")

            page_token = response.get("nextPageToken")
            if not page_token:
                break
