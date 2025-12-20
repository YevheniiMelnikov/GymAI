import asyncio
import logging
import hashlib
import io
from pathlib import Path
from typing import Any, Callable, Final, cast

from google.oauth2.service_account import Credentials  # pyrefly: ignore[import-error]
from googleapiclient.discovery import build  # pyrefly: ignore[import-error]
from googleapiclient.http import MediaIoBaseDownload  # pyrefly: ignore[import-error]
from loguru import logger
from docx import Document  # pyrefly: ignore[import-error]
import fitz  # PyMuPDF  # pyrefly: ignore[import-error]

from config.app_settings import settings
from core.utils.redis_lock import get_redis_client, redis_try_lock
from .base_knowledge_loader import KnowledgeLoader
from .knowledge_base import KnowledgeBase
from .utils.helpers import sanitize_text

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

    def __init__(self, knowledge_base: KnowledgeBase) -> None:
        self._kb = knowledge_base
        self._dataset_name = knowledge_base.GLOBAL_DATASET

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
        attempts = 0
        while not done:
            try:
                status, done = downloader.next_chunk()
            except TimeoutError:
                attempts += 1
                if attempts >= 3:
                    raise
                logger.warning(f"kb_gdrive.download_timeout file_id={file_id} attempt={attempts}")
                await asyncio.sleep(1)
                continue
            if status:
                await asyncio.sleep(0)
        return fh.getvalue()

    _PARSERS: dict[str, Callable[[bytes], str]] = {
        ".txt": _read_txt,
        ".docx": _read_docx,
        ".pdf": _read_pdf,
    }

    async def load(self, force_ingest: bool = False) -> None:
        if not self.folder_id:
            logger.info("No GDRIVE_FOLDER_ID set; skip load")
            return

        async with redis_try_lock("locks:kb_gdrive_load", ttl_ms=300_000, wait=False) as got_lock:
            if not got_lock:
                logger.info("kb_gdrive.skip reason=lock_held")
                return

        service = self._get_drive_files_service()
        q = f"'{self.folder_id}' in parents and trashed = false"
        resp = service.list(q=q, fields="files(id, name, size, mimeType, modifiedTime)").execute()
        files = cast(list[dict[str, Any]], resp.get("files", []))
        logger.debug(f"kb_gdrive.scan start folder_id={self.folder_id} dataset={self._dataset_name} files={len(files)}")
        processed = 0
        skipped = 0
        errors = 0
        user = getattr(self._kb, "_user", None)
        if user is None:
            user = await self._kb.dataset_service.get_cognee_user()
        if user is None:
            logger.warning("kb_gdrive.skip reason=missing_user")
            return
        dataset_alias = self._kb.dataset_service.alias_for_dataset(self._dataset_name)
        fingerprint_items = [
            f"{item.get('id', '')}:{item.get('modifiedTime', '')}:{item.get('size', '')}" for item in files
        ]
        fingerprint = hashlib.sha256("|".join(sorted(fingerprint_items)).encode("utf-8")).hexdigest()
        if not force_ingest:
            cache_key = f"ai_coach:gdrive:folder:{self.folder_id}:fingerprint"
            try:
                client = get_redis_client()
                cached = await client.get(cache_key)
                if cached == fingerprint:
                    logger.info("kb_gdrive.skip reason=fingerprint_match dataset={}", dataset_alias)
                    return
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"kb_gdrive.fingerprint_check_failed detail={exc}")

        for f in files:
            name = f.get("name") or ""
            file_id = f.get("id")
            size = int(f.get("size") or 0)
            ext = Path(name).suffix.lower()

            if ext not in self._PARSERS:
                logger.debug(
                    "kb_gdrive.file_decision dataset={} file={} decision=skip reason=unsupported_extension",
                    dataset_alias,
                    name,
                )
                skipped += 1
                continue
            if (size or 0) > settings.MAX_FILE_SIZE_MB * (1024 * 1024):
                logger.debug(
                    "kb_gdrive.file_decision dataset={} file={} decision=skip reason=file_too_large size_mb={:.1f}",
                    dataset_alias,
                    name,
                    size / 1_048_576,
                )
                skipped += 1
                continue
            if not file_id:
                logger.warning(
                    "kb_gdrive.file_decision dataset={} file={} decision=skip reason=missing_file_id",
                    dataset_alias,
                    name,
                )
                skipped += 1
                continue

            try:
                data = await self._download_file(file_id)
                parser = self._PARSERS[ext]
                text = await asyncio.to_thread(parser, data) if ext != ".txt" else parser(data)
                text = sanitize_text(text)

                normalized = self._kb.dataset_service._normalize_text(text)
                if not normalized.strip():
                    self._kb.dataset_service.log_once(
                        logging.INFO,
                        "kb_gdrive.empty_document",
                        dataset=dataset_alias,
                        file_id=file_id,
                        name=name,
                        source="gdrive",
                        min_interval=120.0,
                    )
                    skipped += 1
                    continue

                metadata = {
                    "dataset": dataset_alias,
                    "source": "gdrive",
                    "file_id": file_id,
                    "name": name,
                    "mime_type": f.get("mimeType"),
                    "size": size,
                }
                modified_ts = f.get("modifiedTime") or f.get("modified_time")
                if modified_ts:
                    metadata["modified_ts"] = modified_ts

                payload_bytes = normalized.encode("utf-8")
                digest_sha = hashlib.sha256(payload_bytes).hexdigest()
                resolved_dataset, created = await self._kb.update_dataset(
                    normalized,
                    self._dataset_name,
                    user,
                    node_set=[f"gdrive:{file_id}"],
                    metadata=metadata,
                    force_ingest=force_ingest,
                )
                is_duplicate = not created
                if is_duplicate and not force_ingest:
                    skipped += 1
                    ident = self._kb.dataset_service.get_registered_identifier(dataset_alias)
                    logger.debug(
                        (
                            "kb_gdrive.file_decision dataset={} file={} decision=skip "
                            "reason=duplicate_digest digest={} ident={}"
                        ),
                        dataset_alias,
                        name,
                        digest_sha[:12],
                        ident,
                    )
                    continue

                processed += 1
                if is_duplicate:
                    ident = self._kb.dataset_service.get_registered_identifier(dataset_alias) or ""
                    logger.debug(
                        (
                            "kb_gdrive.file_decision dataset={} file={} decision=force_ingest "
                            "reason=duplicate_digest digest={} ident={}"
                        ),
                        dataset_alias,
                        name,
                        digest_sha[:12],
                        ident,
                    )
                else:
                    logger.debug(
                        "kb_gdrive.file_decision dataset={} file={} decision=process reason=new_content",
                        dataset_alias,
                        name,
                    )

                try:
                    await self._kb.projection_service.project_dataset(
                        resolved_dataset, user, allow_rebuild=force_ingest
                    )
                    await self._kb._wait_for_projection(resolved_dataset, user, timeout_s=15.0)
                    counts = await self._kb.dataset_service.get_counts(dataset_alias, user)
                    logger.debug(
                        (
                            "projection:ready dataset_alias={} ident={} text_rows={} "
                            "chunk_rows={} graph_nodes={} graph_edges={}"
                        ),
                        dataset_alias,
                        resolved_dataset,
                        counts.get("text_rows"),
                        counts.get("chunk_rows"),
                        counts.get("graph_nodes"),
                        counts.get("graph_edges"),
                    )
                except Exception as exc:
                    logger.debug(f"kb_gdrive.projection_skip dataset={resolved_dataset} detail={exc}")

                logger.debug(
                    "kb_gdrive.ingested dataset_alias={} ident={} file_id={} bytes={} digest={}",
                    dataset_alias,
                    resolved_dataset,
                    file_id,
                    len(payload_bytes),
                    digest_sha[:12],
                )
            except Exception:
                logger.exception(f"Failed to process {name} (id={file_id})")
                errors += 1
        logger.debug(
            "kb_gdrive.summary dataset={} files_total={} processed={} skipped={} errors={}",
            self._dataset_name,
            len(files),
            processed,
            skipped,
            errors,
        )
        try:
            cache_key = f"ai_coach:gdrive:folder:{self.folder_id}:fingerprint"
            client = get_redis_client()
            await client.set(cache_key, fingerprint)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"kb_gdrive.fingerprint_set_failed detail={exc}")

    async def refresh(self, force: bool = False) -> None:
        await self.load(force_ingest=force)
