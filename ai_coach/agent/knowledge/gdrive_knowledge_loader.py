import asyncio
import io
import os

# pyrefly: ignore-file
# ruff: noqa
"""Google Drive knowledge loader."""

from pathlib import Path
from typing import Any, Awaitable, Callable, Final, cast

from google.oauth2.service_account import Credentials  # pyrefly: ignore[import-error]
from googleapiclient.discovery import build  # pyrefly: ignore[import-error]
from googleapiclient.http import MediaIoBaseDownload  # pyrefly: ignore[import-error]
from loguru import logger
from docx import Document  # pyrefly: ignore[import-error]
import fitz  # PyMuPDF  # pyrefly: ignore[import-error]

from config.app_settings import settings
from .base_knowledge_loader import KnowledgeLoader

SCOPES: Final = ["https://www.googleapis.com/auth/drive.readonly"]


def _read_txt(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except Exception:
        return data.decode("latin-1", errors="ignore")


def _read_docx(data: bytes) -> str:
    f = io.BytesIO(data)
    doc = Document(f)
    return "\n".join(p.text for p in doc.paragraphs)


def _read_pdf(data: bytes) -> str:
    f = io.BytesIO(data)
    doc = fitz.open(stream=f, filetype="pdf")
    parts: list[str] = []
    for page in doc:
        parts.append(page.get_text("text"))  # pyrefly: ignore[missing-attribute]
    return "\n".join(parts)


class GDriveDocumentLoader(KnowledgeLoader):
    folder_id: str | None = settings.KNOWLEDGE_BASE_FOLDER_ID
    credentials_path: str | Path = settings.GOOGLE_APPLICATION_CREDENTIALS
    _files_service: Any | None = None
    _add_text: Callable[..., Awaitable[None]]
    _dataset_name: str = os.environ.get("COGNEE_GLOBAL_DATASET", "external_docs")

    def __init__(self, add_text: Callable[..., Awaitable[None]]) -> None:
        self._add_text = add_text

    def _get_drive_files_service(self) -> Any:
        if self._files_service is None:
            creds = Credentials.from_service_account_file(
                str(self.credentials_path),
                scopes=SCOPES,
            )
            self._files_service = build("drive", "v3", credentials=creds).files()
        return self._files_service

    async def _download_file(self, file_id: str) -> bytes:
        service = self._get_drive_files_service()
        request = service.get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                await asyncio.sleep(0)
        return fh.getvalue()

    _PARSERS: dict[str, Callable[[bytes], str]] = {
        ".txt": _read_txt,
        ".docx": _read_docx,
        ".pdf": _read_pdf,
    }

    async def load(self) -> None:
        if not self.folder_id:
            logger.info("No GDRIVE_FOLDER_ID set; skip load")
            return

        service = self._get_drive_files_service()
        q = f"'{self.folder_id}' in parents and trashed = false"
        resp = service.list(q=q, fields="files(id, name, size, mimeType)").execute()
        files = cast(list[dict[str, Any]], resp.get("files", []))

        for f in files:
            name = f.get("name") or ""
            file_id = f.get("id")
            size = int(f.get("size") or 0)
            ext = Path(name).suffix.lower()

            if ext not in self._PARSERS:
                logger.info(f"Skip {name}: unsupported extension")
                continue
            if (size or 0) > settings.MAX_FILE_SIZE_MB * (1024 * 1024):
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
                    dataset=self._dataset_name,
                    user=None,
                    node_set=[f"gdrive:{name}"],
                )
            except Exception as exc:
                logger.error(f"Failed to process {name} (id={file_id}): {exc}")

    async def refresh(self) -> None:
        await self.load()
