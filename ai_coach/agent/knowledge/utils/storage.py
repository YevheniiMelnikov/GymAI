import asyncio
import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Any, Awaitable, Mapping, Sequence, TYPE_CHECKING, Optional

from loguru import logger

from ai_coach.agent.knowledge.cognee_config import CogneeConfig
from ai_coach.agent.knowledge.schemas import DatasetRow, RebuildResult
from ai_coach.agent.knowledge.utils.hash_store import HashStore
from ai_coach.agent.knowledge.utils.storage_resolver import StorageResolver
from ai_coach.agent.knowledge.utils.helpers import normalize_text
from config.app_settings import settings

if TYPE_CHECKING:
    from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase


class StorageService:
    _STORAGE_CACHE: dict[str, str] = {}

    def __init__(self, dataset_service) -> None:
        self.dataset_service = dataset_service
        self._knowledge_base: Optional["KnowledgeBase"] = None

    def attach_knowledge_base(self, knowledge_base: "KnowledgeBase") -> None:
        self._knowledge_base = knowledge_base

    def storage_root(self) -> Path:
        root = CogneeConfig.storage_root()
        if root is not None:
            return root
        return Path(settings.COGNEE_STORAGE_PATH).expanduser().resolve()

    def storage_path_for_sha(self, digest_sha: str) -> Path | None:
        if len(digest_sha) != 64:
            self.dataset_service.log_once(logging.WARNING, "storage_path_invalid_digest", sha=digest_sha)
            return None
        return self.storage_root() / f"text_{digest_sha}.txt"

    async def read_storage_text(self, *, digest_sha: str) -> str | None:
        if digest_sha in self._STORAGE_CACHE:
            return self._STORAGE_CACHE[digest_sha]

        path = self.storage_path_for_sha(digest_sha)
        if path is None:
            return None

        if not path.exists():
            return None

        try:
            text = await asyncio.to_thread(path.read_text, encoding="utf-8")
            self._STORAGE_CACHE[digest_sha] = text
            return text
        except Exception as exc:
            self.dataset_service.log_once(
                logging.DEBUG,
                "storage_read",
                digest=digest_sha[:12],
                detail=exc,
                min_interval=60.0,
            )
            return None

    def ensure_storage_file(
        self, *, digest_sha: str, text: str, dataset: str | None = None
    ) -> tuple[Path | None, bool]:
        path = self.storage_path_for_sha(digest_sha)
        if path is None:
            return None, False

        if path.exists():
            try:
                from hashlib import md5 as _md5

                md5_hex = _md5(text.encode("utf-8")).hexdigest()
                md5_path = path.parent / f"text_{md5_hex}.txt"
                if not md5_path.exists():
                    try:
                        md5_path.symlink_to(path.name)
                        logger.debug(f"md5_mirror_link_created md5={md5_hex[:12]} -> {path.name[:16]}")
                    except Exception:
                        if not md5_path.exists():
                            md5_path.write_text(text, encoding="utf-8")
                            logger.debug(
                                f"md5_mirror_file_created md5={md5_hex[:12]} bytes={len(text.encode('utf-8'))}"
                            )
            except Exception as md5_exc:
                logger.debug(f"md5_mirror_skip reason={md5_exc}")
            return path, False

        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.replace(path)

            try:
                from hashlib import md5 as _md5

                md5_hex = _md5(text.encode("utf-8")).hexdigest()
                md5_path = path.parent / f"text_{md5_hex}.txt"
                if not md5_path.exists():
                    try:
                        md5_path.symlink_to(path.name)
                        logger.debug(f"md5_mirror_link_created md5={md5_hex[:12]} -> {path.name[:16]}")
                    except Exception:
                        if not md5_path.exists():
                            md5_path.write_text(text, encoding="utf-8")
                            logger.debug(
                                f"md5_mirror_file_created md5={md5_hex[:12]} bytes={len(text.encode('utf-8'))}"
                            )
            except Exception as md5_exc:
                logger.debug(f"md5_mirror_skip reason={md5_exc}")

            logger.debug(f"kb_storage ensure sha={digest_sha[:12]} created=True")
            return path, True

        except Exception as exc:
            logger.warning(
                f"knowledge_storage_write_failed digest_sha={digest_sha[:12]} "
                f"dataset={dataset or 'unknown'} path={path} detail={exc}"
            )
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
            return None, False

    async def heal_dataset_storage(
        self, dataset: str, user_ctx: Any | None, *, entries: Sequence[DatasetRow] | None = None, reason: str
    ) -> tuple[int, int]:
        alias = self.dataset_service.alias_for_dataset(dataset)
        if entries is None:
            try:
                fetched = await self.dataset_service.list_dataset_entries(alias, user_ctx)
            except Exception as exc:
                logger.debug(f"knowledge_dataset_heal_fetch_failed dataset={alias} reason={reason} detail={exc}")
                return 0, 0
            entries = fetched
        missing = 0
        healed = 0
        add_tasks: list[Awaitable[None]] = []
        for entry in entries:
            normalized = normalize_text(entry.text)
            metadata_map = entry.metadata if isinstance(entry.metadata, Mapping) else None
            digest_sha_meta = self.metadata_digest_sha(metadata_map)
            if not normalized:
                self.dataset_service.log_once(
                    logging.WARNING,
                    "knowledge_dataset_heal_unrecoverable",
                    dataset=alias,
                    digest=digest_sha_meta[:12] if digest_sha_meta else "N/A",
                    reason="empty_content",
                )
                continue
            digest_sha = self.compute_digests(normalized, dataset_alias=alias)
            storage_path = self.storage_path_for_sha(digest_sha)
            if storage_path is None:
                continue
            sha_exists = storage_path.exists()
            if not sha_exists:
                missing += 1
            _, created = self.ensure_storage_file(
                digest_sha=digest_sha,
                text=normalized,
                dataset=alias,
            )
            if created:
                healed += 1
            metadata_payload = self.augment_metadata(entry.metadata, alias, digest_sha=digest_sha)
            add_tasks.append(HashStore.add(alias, digest_sha, metadata=metadata_payload))
        if add_tasks:
            await asyncio.gather(*add_tasks)
        if missing or healed:
            logger.debug(
                f"knowledge_dataset_storage_heal dataset={alias} reason={reason} missing={missing} healed={healed}"
            )
            self.log_storage_state(alias, missing_count=missing, healed_count=healed)
        return missing, healed

    async def rebuild_from_disk(self, alias: str) -> tuple[int, int]:
        storage_root = self.storage_root()
        if not storage_root.exists():
            return 0, 0
        created = 0
        linked = 0
        mismatch_count = 0
        unreadable_count = 0
        empty_count = 0
        for path in storage_root.glob("text_*.txt"):
            digest_match = re.match(r"^text_([0-9a-f]{64})\.txt$", path.name)
            if not digest_match:
                if re.match(r"^text_([0-9a-f]{32})\.txt$", path.name):
                    self.dataset_service.log_once(logging.INFO, "rebuild_disk_md5_ignored", path=path.name)
                continue
            digest_sha_from_name = digest_match.group(1)
            try:
                contents = await asyncio.to_thread(path.read_text, encoding="utf-8")
            except Exception as exc:
                logger.debug(
                    f"knowledge_rebuild_read_failed dataset={alias} sha={digest_sha_from_name[:12]} detail={exc}"
                )
                unreadable_count += 1
                continue
            normalized = normalize_text(contents)
            if not normalized:
                empty_count += 1
                continue
            digest_sha_from_content = self.compute_digests(normalized, dataset_alias=alias)
            if digest_sha_from_content != digest_sha_from_name:
                logger.warning(
                    f"knowledge_rebuild_digest_mismatch dataset={alias} "
                    f"path_sha={digest_sha_from_name[:12]} content_sha={digest_sha_from_content[:12]}"
                )
                mismatch_count += 1
                continue
            inferred_metadata = self.dataset_service._infer_metadata_from_text(
                normalized,
                {"dataset": alias},
            )
            metadata = self.augment_metadata(
                inferred_metadata,
                alias,
                digest_sha=digest_sha_from_content,
            )
            try:
                already = await HashStore.contains(alias, digest_sha_from_content)
                await HashStore.add(alias, digest_sha_from_content, metadata=metadata)
            except Exception as exc:
                logger.debug(
                    "knowledge_rebuild_hashstore_failed "
                    f"dataset={alias} sha={digest_sha_from_content[:12]} detail={exc}"
                )
                continue
            linked += 1
            if not already:
                created += 1
        if created > 0 or linked > 0 or mismatch_count > 0 or unreadable_count > 0 or empty_count > 0:
            logger.info(
                "rebuild:summary dataset={} created={} linked={} mismatches={} unreadable={} empty={}",
                alias,
                created,
                linked,
                mismatch_count,
                unreadable_count,
                empty_count,
            )
        return created, linked

    async def reingest_from_hashstore(
        self,
        alias: str,
        user: Any | None,
        digests: Sequence[tuple[str, Mapping[str, Any] | None]],
        *,
        knowledge_base: Optional["KnowledgeBase"] = None,
    ) -> RebuildResult:
        result = RebuildResult()
        if not digests:
            return result

        kb = knowledge_base or self._knowledge_base
        if kb is None:
            result.healed = False
            result.reason = "knowledge_base_unavailable"
            logger.debug(f"knowledge_reingest_failed dataset={alias} reason=knowledge_base_unavailable")
            return result

        actor = user if user is not None else getattr(kb, "_user", None)
        if actor is None:
            result.healed = False
            result.reason = "update_dataset_failed_missing_user"
            logger.debug(f"knowledge_reingest_failed dataset={alias} reason=missing_user")
            return result

        for digest_sha, metadata in digests:
            if len(digest_sha) != 64:
                logger.warning("hashstore_legacy_digest_skipped digest={}", digest_sha[:12])
                continue
            path = self.storage_path_for_sha(digest_sha)
            if path is None:
                continue
            logger.debug(f"[reingest_probe] sha={digest_sha} path_attempt={path}")
            normalized = None
            if path.exists():
                try:
                    raw_text = await self.read_storage_text(digest_sha=digest_sha)
                    if raw_text:
                        normalized = normalize_text(raw_text)
                except Exception as exc:
                    logger.debug(f"knowledge_reingest_read_failed dataset={alias} sha={digest_sha[:12]} detail={exc}")
            else:
                md5_path = StorageResolver.map_sha_to_md5_path(digest_sha, self.storage_root())
                if md5_path and md5_path.exists():
                    try:
                        raw_text = await asyncio.to_thread(md5_path.read_text, encoding="utf-8")
                        normalized = normalize_text(raw_text)
                        logger.debug(f"reingest_md5_fallback_ok sha={digest_sha[:12]} md5_path={md5_path.name[:12]}")
                    except Exception as exc:
                        logger.debug(
                            "knowledge_reingest_read_failed_md5_fallback "
                            f"dataset={alias} sha={digest_sha[:12]} detail={exc}"
                        )

            if not normalized and metadata and metadata.get("text"):
                normalized = normalize_text(str(metadata["text"]))
                if normalized:
                    self.ensure_storage_file(digest_sha=digest_sha, text=normalized, dataset=alias)
                    result.healed_documents += 1
            elif not normalized and not metadata:
                if await HashStore.contains(alias, digest_sha):
                    await HashStore.remove(alias, digest_sha)
                    self.dataset_service.log_once(
                        logging.WARNING,
                        "knowledge_reingest_stale_md5_removed",
                        dataset=alias,
                        digest_sha=digest_sha[:12],
                        reason="no_metadata_to_heal",
                    )
                continue

            if not normalized:
                self.dataset_service.log_once(
                    logging.WARNING,
                    "knowledge_reingest_unrecoverable",
                    dataset=alias,
                    digest_sha=digest_sha[:12],
                )
                continue

            kind = metadata.get("kind") if isinstance(metadata, Mapping) else None
            if kind == "message":
                continue
            meta_payload = dict(metadata) if isinstance(metadata, Mapping) else None
            try:
                dataset_name, created = await kb.update_dataset(
                    normalized,
                    alias,
                    user=actor,
                    node_set=None,
                    metadata=meta_payload,
                )
            except Exception as exc:
                result.healed = False
                result.reason = getattr(exc, "args", ("update_dataset_failed",))[0]
                logger.debug(f"knowledge_reingest_failed dataset={alias} digest_sha={digest_sha[:12]} detail={exc}")
                break
            if created:
                result.reinserted += 1
                self.dataset_service.register_dataset_identifier(alias, dataset_name)
                result.last_dataset = dataset_name

        if result.reinserted:
            result.rehydrated = result.reinserted
        if result.reason is None:
            result.reason = "ok"
        if result.reinserted or result.healed_documents or result.rehydrated:
            logger.info(
                "reingest:summary dataset={} reinserted={} healed={} rehydrated={} last_dataset={} reason={}",
                alias,
                result.reinserted,
                result.healed_documents,
                result.rehydrated,
                result.last_dataset or "",
                result.reason or "ok",
            )
        # Ensure alias→identifier mapping is registered even if no new documents were created in this run
        try:
            if result.last_dataset:
                self.dataset_service.register_dataset_identifier(alias, result.last_dataset)
        except Exception as exc:
            logger.debug(
                f"reingest_register_identifier_failed dataset={alias} ident={result.last_dataset} detail={exc}"
            )
        return result

    def filename_to_digest(self, filename: str | None) -> str | None:
        if not filename:
            return None
        if filename.startswith("text_") and filename.endswith(".txt"):
            return filename[5:-4]
        return None

    def digest_from_raw_location(self, raw_location: str | None) -> str | None:
        from urllib.parse import urlparse

        if not raw_location:
            return None
        try:
            parsed = urlparse(raw_location)
        except Exception:
            return None
        if parsed.scheme == "file":
            return self.filename_to_digest(Path(parsed.path).name)
        return self.filename_to_digest(Path(raw_location).name)

    @staticmethod
    def metadata_digest_sha(metadata: Mapping[str, Any] | None) -> str | None:
        if not metadata:
            return None
        value = metadata.get("digest_sha")
        if isinstance(value, str):
            candidate = value.strip()
            if candidate:
                return candidate
        return None

    @staticmethod
    def compute_digests(normalized_text: str, *, dataset_alias: str | None = None) -> str:
        payload = normalized_text.encode("utf-8")
        digest_sha = hashlib.sha256(payload).hexdigest()
        return digest_sha

    def log_storage_state(
        self, dataset: str, *, missing_count: int | None = None, healed_count: int | None = None
    ) -> None:
        storage_info = CogneeConfig.describe_storage()
        logger.warning(
            f"knowledge_dataset_storage_state dataset={dataset} storage_root={storage_info.get('root')} "
            f"root_exists={storage_info.get('root_exists')} root_writable={storage_info.get('root_writable')} "
            f"entries={storage_info.get('entries_count')} sample={storage_info.get('entries_sample')} "
            f"package_path={storage_info.get('package_path')} package_exists={storage_info.get('package_exists')} "
            f"package_is_symlink={storage_info.get('package_is_symlink')} "
            f"package_target={storage_info.get('package_target')} missing_count={missing_count} "
            f"healed_count={healed_count}"
        )

    async def sanitize_hash_store(self) -> None:
        md5_found_count = 0
        md5_converted_count = 0
        md5_removed_count = 0
        sha_final_count = 0

        all_aliases = await HashStore.list_all_datasets() if hasattr(HashStore, "list_all_datasets") else []
        for alias in all_aliases:
            digests_to_process = await HashStore.list(alias)
            for digest in digests_to_process:
                if len(digest) == 32:
                    md5_found_count += 1
                    metadata = await HashStore.metadata(alias, digest)
                    if metadata and metadata.get("text"):
                        content = str(metadata["text"])
                        sha256_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                        if await HashStore.contains(alias, sha256_hash):
                            await HashStore.remove(alias, digest)
                            md5_removed_count += 1
                        else:
                            await HashStore.remove(alias, digest)
                            await HashStore.add(alias, sha256_hash, metadata)
                            md5_converted_count += 1
                    else:
                        await HashStore.remove(alias, digest)
                        md5_removed_count += 1
            sha_final_count += len(await HashStore.list(alias))

        if md5_found_count > 0:
            logger.info(
                f"kb_hashstore_sanitation_completed md5_found={md5_found_count} "
                f"md5_converted={md5_converted_count} md5_removed={md5_removed_count} "
                f"sha_final={sha_final_count}"
            )
        else:
            logger.info("kb_hashstore_sanitation_skipped reason=no_md5_entries_found")

    @staticmethod
    def augment_metadata(
        metadata: Mapping[str, Any] | None, dataset_alias: str | None, *, digest_sha: str
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if metadata:
            payload.update(dict(metadata))
        dataset_value = (dataset_alias or payload.get("dataset") or "").strip()
        if dataset_value:
            payload["dataset"] = dataset_value
        else:
            payload.pop("dataset", None)
        payload["digest_sha"] = digest_sha
        if "kind" not in payload:
            payload["kind"] = "document"
        return payload
