from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any, Awaitable, Callable, Final, cast

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from loguru import logger
from docx import Document
import fitz  # PyMuPDF

from config.app_settings import settings
from .base_knowledge_loader import KnowledgeLoader

SCOPES: Final = ["https://www.googleapis.com/auth/drive.readonly"]
ALLOWED_EXTS: Final = {".pdf", ".docx", ".txt"}
CHUNK_SIZE: Final = 1 * 1024 * 1024  # 1MB per chunk when downloading


class GDriveDocumentLoader(KnowledgeLoader):
    """Load documents from Google Drive into Cognee."""

    folder_id: str | None = settings.GDRIVE_FOLDER_ID
    credentials_path: str | Path = settings.GOOGLE_APPLICATION_CREDENTIALS
    _files_service: Any | None = None
    _add_text: Callable[..., Awaitable[None]]

    def __init__(self, add_text: Callable[..., Awaitable[None]]) -> None:
        self._add_text = add_text

    def _get_drive_files_service(self) -> Any:
        if self._files_service is None:
            creds = Credentials.from_service_account_file(  # type: ignore[arg-type]
                filename=self.credentials_path,
                scopes=SCOPES,
            )
            service = build("drive", "v3", credentials=creds)
            self._files_service = service.files()
        return self._files_service

    async def _download_file(self, file_id: str) -> bytes:
        files_service = self._get_drive_files_service()

        def _blocking_download() -> bytes:
            request = files_service.get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request, chunksize=CHUNK_SIZE)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return fh.getvalue()

        return await asyncio.to_thread(_blocking_download)

    @staticmethod
    def _parse_pdf(data: bytes) -> str:
        with fitz.open(stream=data, filetype="pdf") as doc:
            return "\n".join(cast(Any, page).get_text("text") for page in doc)

    @staticmethod
    def _parse_docx(data: bytes) -> str:
        document = Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs)

    @staticmethod
    def _parse_txt(data: bytes) -> str:
        return data.decode("utf-8", errors="ignore")

    _PARSERS: dict[str, Callable[[bytes], str]] = {}

    async def load(self) -> None:
        if not self._PARSERS:
            self._PARSERS = {
                ".pdf": self._parse_pdf,
                ".docx": self._parse_docx,
                ".txt": self._parse_txt,
            }

        files_service = self._get_drive_files_service()
        page_token: str | None = None

        while True:
            response: dict[str, Any] = await asyncio.to_thread(
                lambda: files_service.list(
                    q=f"'{self.folder_id}' in parents and trashed=false",
                    fields="nextPageToken, files(id, name, mimeType, size)",
                    pageToken=page_token,
                ).execute()
            )

            for file_meta in response.get("files", []):
                name: str = file_meta.get("name", "")
                file_id: str | None = file_meta.get("id")
                size: int = int(file_meta.get("size", 0))
                ext: str = Path(name).suffix.lower()

                if ext not in ALLOWED_EXTS:
                    logger.debug(f"Skip {name}: unsupported extension {ext}")
                    continue
                if size / (1024 * 1024) > settings.MAX_FILE_SIZE_MB:
                    logger.info(f"Skip {name}: file too large ({size / 1_048_576:.1f}MB)")
                    continue
                if not file_id:
                    logger.warning(f"Skip {name}: missing file_id")
                    continue

                try:
                    data = await self._download_file(file_id)
                    parser = self._PARSERS[ext]
                    text = await asyncio.to_thread(parser, data) if ext != ".txt" else parser(data)

                    if not text.strip():
                        logger.debug(f"Skip {name}: empty after parsing")
                        continue

                    await self._add_text(
                        text,
                        client_id=None,
                        node_set=[f"gdrive:{name}"],
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error(f"Failed to process {name} (id={file_id}): {exc}")

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    async def refresh(self) -> None:
        """Refresh documents from Google Drive."""
        await self.load()
