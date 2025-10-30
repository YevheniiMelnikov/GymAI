import asyncio
import hashlib
import inspect
import logging
import os
import random
import re
import time
from dataclasses import asdict, dataclass, is_dataclass
from hashlib import sha256
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, ClassVar, Iterable, Mapping, Sequence, cast
from urllib.parse import urlparse
from uuid import UUID

from loguru import logger

from ai_coach.agent.knowledge.base_knowledge_loader import KnowledgeLoader
from ai_coach.agent.knowledge.cognee_config import CogneeConfig
from ai_coach.agent.knowledge.utils.hash_store import HashStore
from ai_coach.agent.knowledge.utils.lock_cache import LockCache
from ai_coach.agent.knowledge.utils.storage_resolver import StorageResolver
from ai_coach.agent.knowledge.utils.text import normalize_text
from ai_coach.schemas import CogneeUser
from ai_coach.types import MessageRole
from config.app_settings import settings
from core.exceptions import UserServiceError
from core.services import APIService
from core.schemas import Client

from typing import Literal

import cognee  # type: ignore

try:
    from cognee.modules.users.methods.get_default_user import get_default_user  # type: ignore
except Exception:

    async def get_default_user() -> Any | None:  # type: ignore
        return None


try:  # pragma: no cover - optional dependency
    from cognee.modules.data.exceptions import DatasetNotFoundError  # type: ignore
    from cognee.modules.users.exceptions.exceptions import PermissionDeniedError  # type: ignore
except Exception:  # pragma: no cover - stubs for tests

    class DatasetNotFoundError(Exception):
        pass

    class PermissionDeniedError(Exception):
        pass


async def _safe_add(*args, **kwargs):
    return await cognee.add(*args, **kwargs)


class ProjectionProbeError(RuntimeError):
    """Raised when dataset readiness cannot be determined due to configuration issues."""


from enum import Enum


class ProjectionStatus(Enum):
    READY = "ready"
    TIMEOUT = "timeout"
    FATAL_ERROR = "fatal_error"
    USER_CONTEXT_UNAVAILABLE = "user_context_unavailable"


@dataclass(slots=True)
class KnowledgeSnippet:
    text: str
    dataset: str | None = None
    kind: Literal["document", "message", "note", "unknown"] = "document"

    def is_content(self) -> bool:
        return self.kind in {"document", "note"}


@dataclass(slots=True)
class DatasetRow:
    text: str
    metadata: Mapping[str, Any] | None = None


@dataclass(slots=True)
class RebuildResult:
    reinserted: int = 0
    healed: int = 0
    linked: int = 0
    rehydrated: int = 0


class KnowledgeBase:
    """Cognee-backed knowledge storage for the coach agent."""

    _loader: KnowledgeLoader | None = None
    _cognify_locks: LockCache = LockCache()
    _user: Any | None = None
    _list_data_supports_user: bool | None = None
    _list_data_requires_user: bool | None = None
    _has_datasets_module: bool | None = None
    _warned_missing_user: bool = False
    _DATASET_IDS: ClassVar[dict[str, str]] = {}
    _DATASET_ALIASES: ClassVar[dict[str, str]] = {}
    _PROJECTED_DATASETS: ClassVar[set[str]] = set()
    _PENDING_REBUILDS: ClassVar[set[str]] = set()
    _PROJECTION_STATE: ClassVar[dict[str, dict[str, Any]]] = {}
    _LOG_THROTTLE: ClassVar[dict[str, float]] = {}
    _DATASET_IDENTIFIER_FIELDS: ClassVar[tuple[str, ...]] = (
        "dataset_id",
        "datasetId",
        "dataset_name",
        "datasetName",
        "id",
    )
    GLOBAL_DATASET: str = settings.COGNEE_GLOBAL_DATASET
    _CLIENT_ALIAS_PREFIX: str = "kb_client_"
    _CHAT_ALIAS_PREFIX: str = "kb_chat_"
    _LEGACY_CLIENT_PREFIX: str = "client_"
    _PROJECTION_CHECK_QUERY: str = "__knowledge_projection_health__"
    _PROJECTION_BACKOFF_SECONDS: tuple[float, ...] = (0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 12.0)
    _CHAT_PENDING: ClassVar[dict[str, int]] = {}
    _CHAT_PROJECT_TASKS: ClassVar[dict[str, asyncio.Task[Any]]] = {}
    _CHAT_LAST_PROJECT_TS: ClassVar[dict[str, float]] = {}
    _SHA_PRIMARY: ClassVar[bool] = getattr(settings, "COGNEE_STORAGE_SHA_PRIMARY", True)
    _LAST_REBUILD_RESULT: ClassVar[dict[str, Any]] = {}
    _GLOBAL_PROJECTION_LOGGED_INFO: ClassVar[bool] = False

    @classmethod
    async def _get_consistency_report(cls) -> dict[str, Any]:
        storage_root = cls._storage_root()
        storage_sha_files = 0
        if storage_root.exists():
            for path in storage_root.glob("text_*.txt"):
                if re.match(r"^text_([0-9a-f]{64})\.txt$", path.name):
                    storage_sha_files += 1

        hashstore_entries_sha = 0
        hashstore_entries_md5 = 0
        all_datasets = (
            await HashStore.list_all_datasets()
            if hasattr(HashStore, "list_all_datasets")
            else [cls._alias_for_dataset(cls.GLOBAL_DATASET)]
        )
        for dataset_alias in all_datasets:
            digests = await HashStore.list(dataset_alias)
            for digest in digests:
                if len(digest) == 64:
                    hashstore_entries_sha += 1
                elif len(digest) == 32:
                    hashstore_entries_md5 += 1

        can_rebuild = storage_root.exists() and os.access(storage_root, os.W_OK)

        return {
            "storage_sha_files": storage_sha_files,
            "hashstore_entries_sha": hashstore_entries_sha,
            "hashstore_entries_md5": hashstore_entries_md5,
            "can_rebuild": can_rebuild,
            "last_rebuild_result": cls._LAST_REBUILD_RESULT,
        }

    @classmethod
    async def initialize(cls, knowledge_loader: KnowledgeLoader | None = None) -> None:
        """Initialize Cognee config, user, and preload knowledge base."""
        CogneeConfig.apply()
        try:
            from cognee.modules.engine.operations.setup import setup as cognee_setup  # type: ignore

            await cognee_setup()
        except Exception:
            pass
        cls._loader = knowledge_loader
        cls._user = await cls._get_cognee_user()
        if not getattr(cls._user, "id", None):
            logger.warning("KB user is missing id, skipping heavy initialization steps.")
            return

        cls._PROJECTED_DATASETS.clear()
        try:
            await cls._sanitize_hash_store()
        except Exception as exc:  # noqa: BLE001 - best effort sanitation
            logger.warning(f"kb_hashstore_sanitation_failed detail={exc}")

        if hasattr(StorageResolver, "build_md5_to_sha_index"):
            try:
                build_func = StorageResolver.build_md5_to_sha_index
                if inspect.iscoroutinefunction(build_func):
                    await build_func(cls._storage_root())
                else:
                    build_func(cls._storage_root())
            except Exception as exc:
                logger.warning(f"StorageResolver.build_md5_to_sha_index failed: {exc}")

        try:
            await cls.rebuild_dataset(cls.GLOBAL_DATASET, cls._user, sha_only=True)
        except Exception as exc:  # noqa: BLE001 - best effort rebuild
            logger.warning(f"kb_global_rebuild_failed detail={exc}")
        try:
            await cls.refresh()
        except Exception as e:
            logger.warning(f"Knowledge refresh skipped: {e}")
        ds_id = await cls._get_dataset_id(cls.GLOBAL_DATASET, cls._user)
        if ds_id:
            timeout = float(getattr(settings, "AI_COACH_GLOBAL_PROJECTION_FIRST_BOOT_TIMEOUT", 5.0))
            try:
                status = await cls._wait_for_projection(cls.GLOBAL_DATASET, cls._user, timeout_s=timeout)
                if status == ProjectionStatus.READY:
                    logger.info(f"projection:first_boot_wait_s={timeout}")
                else:
                    logger.warning(f"Knowledge global projection wait failed: {status.value}")
            except Exception as exc:  # noqa: BLE001 - diagnostics only
                logger.warning(f"Knowledge global projection wait failed: {exc}")
        else:
            logger.warning("kb_global_projection_skipped reason=dataset_id_unavailable")

        storage_root = cls._storage_root()
        storage_info = CogneeConfig.describe_storage()
        projection_status = await cls._is_projection_ready(cls.GLOBAL_DATASET, user=cls._user)
        kb_projection_rows = 0
        try:
            kb_projection_rows = len(await cls._list_dataset_entries(cls.GLOBAL_DATASET, cls._user))
        except Exception:
            pass

        logger.info(
            f"kb_storage_root={storage_root}, "
            f"files_count={storage_info.get('entries_count', 0)}, "
            f"md5_mirrors_count={storage_info.get('md5_mirrors_count', 0)}, "
            f"kb_projection_rows={kb_projection_rows}, "
            f"projection_status={projection_status}"
        )

    @classmethod
    async def refresh(cls) -> None:
        """Re-cognify global dataset and refresh loader if available."""
        user = await cls._get_cognee_user()
        ds = cls._resolve_dataset_alias(cls.GLOBAL_DATASET)
        await cls._ensure_dataset_exists(ds, user)
        cls._PROJECTED_DATASETS.discard(cls._alias_for_dataset(ds))
        if cls._loader:
            await cls._loader.refresh()
        user_ctx = cls._to_user_ctx(user)
        if user_ctx is None:
            logger.warning(f"knowledge_refresh_skipped dataset={ds}: user context unavailable")
            return
        target = ds
        try:
            dataset_id = await cls._get_dataset_id(ds, user)
        except ProjectionProbeError:
            dataset_id = None
        if dataset_id:
            target = dataset_id
        try:
            await cognee.cognify(datasets=[target], user=user_ctx)  # pyrefly: ignore[bad-argument-type]
        except (PermissionDeniedError, DatasetNotFoundError) as e:
            logger.error(f"Knowledge base update skipped: {e}")

    @classmethod
    async def ensure_global_projected(cls, *, timeout: float | None = None) -> bool:
        user = await cls._get_cognee_user()
        dataset = cls._resolve_dataset_alias(cls.GLOBAL_DATASET)
        try:
            await cls._ensure_dataset_exists(dataset, user)
        except Exception as exc:  # noqa: BLE001
            cls._log_once(
                logging.DEBUG,
                "knowledge_projection_dataset_missing",
                throttle_key=f"projection:{dataset}:ensure_missing",
                dataset=dataset,
                detail=exc,
            )
        user_ctx = cls._to_user_ctx(user)
        status = await cls._wait_for_projection(dataset, user=user, timeout_s=timeout)
        if status == ProjectionStatus.READY:
            cls._PROJECTED_DATASETS.add(cls._alias_for_dataset(dataset))
            return True

        if user is not None:
            try:
                entries = await cls._list_dataset_entries(dataset, user)
            except Exception as exc:  # noqa: BLE001 - diagnostics only
                cls._log_once(
                    logging.DEBUG,
                    "projection:ensure_list_failed",
                    dataset=dataset,
                    reason="list_entries_failed",
                    detail=exc,
                    min_interval=15.0,
                )
            else:
                if entries:
                    missing, healed = await cls._heal_dataset_storage(
                        dataset,
                        user,
                        entries=entries,
                        reason="ensure_global_projection",
                    )
                    if healed > 0:
                        retry_timeout = 5.0
                        if timeout is not None:
                            retry_timeout = min(max(timeout, 0.0), 5.0)
                        retry_status = await cls._wait_for_projection(
                            dataset,
                            user=user,
                            timeout_s=retry_timeout,
                        )
                        if retry_status == ProjectionStatus.READY:
                            alias = cls._alias_for_dataset(dataset)
                            cls._PROJECTED_DATASETS.add(alias)
                            return True

        cls._log_once(
            logging.INFO if not cls._GLOBAL_PROJECTION_LOGGED_INFO else logging.DEBUG,
            "projection:deferred",
            dataset=dataset,
        )
        if not cls._GLOBAL_PROJECTION_LOGGED_INFO:
            cls._GLOBAL_PROJECTION_LOGGED_INFO = True
        state = cls._projection_state(cls._alias_for_dataset(dataset))
        state["next_check_ts"] = time.time() + random.uniform(15.0, 30.0)
        if user is not None and not state.get("processing"):
            state["processing"] = True

            async def _background_process() -> None:
                try:
                    await cls._process_dataset(dataset, user)
                finally:
                    state["processing"] = False

            task = asyncio.create_task(_background_process())
            task.add_done_callback(cls._log_task_exception)
        return False

    @classmethod
    async def prune(cls) -> None:
        """Run Cognee prune routine to cleanup cached data."""
        try:
            from cognee.api.v1.prune import prune as cognee_prune  # noqa
        except Exception as exc:  # pragma: no cover - import errors handled upstream
            logger.error(f"Cognee prune unavailable: {exc}")
            raise UserServiceError("Cognee prune module unavailable") from exc

        try:
            await cognee_prune.prune_data()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Cognee prune failed: {exc}")
            raise UserServiceError("Cognee prune failed") from exc

    @classmethod
    async def update_dataset(
        cls,
        text: str,
        dataset: str,
        user: Any | None,
        node_set: list[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[str, bool]:
        """Add text to dataset if new, update hash store, return (dataset, created)."""
        normalized_text = cls._normalize_text(text)
        if not normalized_text.strip():
            logger.debug(f"empty_content_filtered dataset={dataset}")
            return dataset, False
        digest_sha = cls._compute_digests(normalized_text)
        payload = normalized_text.encode("utf-8")
        ds_name = cls._resolve_dataset_alias(dataset)
        await cls._ensure_dataset_exists(ds_name, user)
        storage_path, created_file = cls._ensure_storage_file(
            digest_sha=digest_sha,
            text=normalized_text,
            dataset=ds_name,
        )
        if storage_path is None:
            return ds_name, False
        logger.debug(f"[sha_path_check] dataset={ds_name} sha={digest_sha[:12]} built_path={storage_path}")
        if created_file:
            logger.debug(
                f"kb_write start dataset={ds_name} digest_sha={digest_sha[:12]} "
                f"path={storage_path} bytes={len(payload)}"
            )
        metadata_payload = cls._augment_metadata(metadata, ds_name, digest_sha=digest_sha)
        if await HashStore.contains(ds_name, digest_sha):
            await HashStore.add(ds_name, digest_sha, metadata=metadata_payload)
            logger.debug(f"kb_append skipped dataset={ds_name} digest_sha={digest_sha[:12]} reason=duplicate")
            return ds_name, False

        info: Any | None = None
        for attempt in range(2):  # Allow one retry for MD5 fallback
            try:
                info = await _safe_add(
                    normalized_text,
                    dataset_name=ds_name,
                    user=cls._to_user_ctx(user),  # pyrefly: ignore[bad-argument-type]
                    node_set=node_set,
                )
                break  # Success, exit loop
            except FileNotFoundError as exc:
                missing_path_str = getattr(exc, "filename", None) or str(exc)
                missing_filename = Path(missing_path_str).name
                if StorageResolver.is_md5_filename(missing_filename):
                    # 1) записываем недостающий md5-файл напрямую
                    md5_path = Path(missing_path_str)
                    if not md5_path.is_absolute():
                        md5_path = cls._storage_root() / missing_filename
                    try:
                        md5_path.parent.mkdir(parents=True, exist_ok=True)
                        md5_path.write_text(normalized_text, encoding="utf-8")
                        bytes_written = len(normalized_text.encode("utf-8"))
                        logger.debug(f"storage_md5_fallback_written md5={missing_filename[:12]} bytes={bytes_written}")
                        continue  # повторяем _safe_add
                    except Exception as write_exc:
                        logger.debug(
                            f"storage_md5_fallback_write_failed md5={missing_filename[:12]} detail={write_exc}"
                        )
                    # 2) как запасной путь — старая ветка с маппингом/HashStore
                    sha_path = StorageResolver.map_md5_to_sha_path(missing_filename, cls._storage_root())
                    if sha_path and sha_path.exists():
                        logger.debug(f"storage_md5_fallback_ok sha={sha_path.name[:12]} md5={missing_filename[:12]}")
                        continue  # Retry _safe_add, now with SHA file present
                    else:
                        # SHA file not found or mapping failed, try to restore from HashStore
                        md5_digest = cls._filename_to_digest(missing_filename)
                        if md5_digest:
                            # Get metadata for the MD5 digest
                            metadata_from_hashstore = await HashStore.metadata(ds_name, md5_digest)
                            if metadata_from_hashstore and metadata_from_hashstore.get("text"):
                                restored_text = str(metadata_from_hashstore["text"])
                                # Recompute SHA from restored text to ensure consistency
                                recomputed_sha = cls._compute_digests(cls._normalize_text(restored_text))
                                # Ensure the SHA file exists with the restored content
                                restored_sha_path, created_restored_file = cls._ensure_storage_file(
                                    digest_sha=recomputed_sha,
                                    text=restored_text,
                                    dataset=ds_name,
                                )
                                if created_restored_file:
                                    logger.debug(
                                        f"storage_md5_fallback_healed sha={recomputed_sha[:12]} md5={md5_digest[:12]}"
                                    )
                                    # Update HashStore to use SHA digest if not already
                                    await HashStore.add(ds_name, recomputed_sha, metadata=metadata_from_hashstore)
                                    # Remove old MD5 entry if it exists
                                    await HashStore.remove(ds_name, md5_digest)
                                    continue  # Retry _safe_add, now with SHA file present
                                else:
                                    logger.warning(
                                        f"storage_md5_fallback_restore_failed sha={recomputed_sha[:12]} md5={md5_digest[:12]} reason=file_not_created"
                                    )
                            else:
                                logger.debug(
                                    f"storage_md5_fallback_miss md5={missing_filename[:12]} reason=no_metadata_text"
                                )
                        else:
                            logger.debug(
                                f"storage_md5_fallback_miss md5={missing_filename[:12]} reason=invalid_md5_filename"
                            )
                logger.debug(
                    f"kb_append storage_missing dataset={ds_name} sha={digest_sha[:12]} detail={exc}",
                )
                raise  # Re-raise if not an MD5 fallback or fallback failed
            except (DatasetNotFoundError, PermissionDeniedError):
                raise
        if info is None:
            # If we reach here, it means all retries failed or an unhandled exception occurred
            raise RuntimeError(f"Failed to add dataset entry after retries for {ds_name}")

        hashstore_ok = False
        for attempt in range(2):
            await HashStore.add(ds_name, digest_sha, metadata=metadata_payload)
            try:
                hashstore_ok = await HashStore.contains(ds_name, digest_sha)
            except Exception as exc:  # noqa: BLE001 - diagnostics only
                logger.warning(
                    f"hashstore_add_verification_failed dataset={ds_name} digest_sha={digest_sha[:12]} detail={exc}"
                )
                continue
            if hashstore_ok:
                break
        if not hashstore_ok:
            logger.warning(
                f"hashstore_add_failed dataset={ds_name} digest_sha={digest_sha[:12]} will_mark_for_rebuild=True"
            )
            alias = cls._alias_for_dataset(ds_name)
            if alias not in cls._PENDING_REBUILDS and user is not None:
                cls._PENDING_REBUILDS.add(alias)

                async def _schedule_rebuild() -> None:
                    try:
                        await cls.rebuild_dataset(alias, user)
                    except Exception as rebuild_exc:  # noqa: BLE001 - background diagnostics only
                        logger.debug(f"knowledge_dataset_rebuild_deferred_failed dataset={alias} detail={rebuild_exc}")
                    finally:
                        cls._PENDING_REBUILDS.discard(alias)

                asyncio.create_task(_schedule_rebuild())
        resolved = ds_name
        identifier = cls._extract_dataset_identifier(info)
        if identifier:
            cls._register_dataset_identifier(ds_name, identifier)
            resolved = identifier
        logger.debug(f"kb_append ds={resolved} item=1")
        logger.debug(f"kb_append ok dataset={resolved} digest_sha={digest_sha[:12]} path={storage_path}")
        return resolved, True

    @classmethod
    async def search(
        cls,
        query: str,
        client_id: int,
        k: int | None = None,
        *,
        request_id: str | None = None,
    ) -> list[KnowledgeSnippet]:
        """Search across client and global datasets with resiliency features."""
        normalized = query.strip()
        if not normalized:
            logger.debug(f"Knowledge search skipped client_id={client_id}: empty query")
            return []
        rid_value = request_id or "na"
        global_alias = cls._alias_for_dataset(cls._resolve_dataset_alias(cls.GLOBAL_DATASET))
        global_ready = global_alias in cls._PROJECTED_DATASETS
        global_unavailable = False

        if not global_ready:
            ready = await cls.ensure_global_projected(timeout=0.3)  # Quick check, no blocking
            if ready:
                cls._PROJECTED_DATASETS.add(global_alias)
                global_ready = True
            else:
                global_unavailable = True
                cls._log_once(
                    logging.INFO,
                    "knowledge_search_global_pending",
                    throttle_key=f"projection:{global_alias}:search_pending",
                    client_id=client_id,
                    rid=rid_value,
                )
        user = await cls._get_cognee_user()
        await cls._ensure_profile_indexed(client_id, user)
        datasets = [cls._dataset_name(client_id), cls._chat_dataset_name(client_id)]
        if global_ready:
            datasets.append(cls.GLOBAL_DATASET)
        resolved_datasets: list[str] = []
        for alias in datasets:
            resolved = cls._resolve_dataset_alias(alias)
            try:
                await cls._ensure_dataset_exists(resolved, user)
            except Exception as ensure_exc:
                logger.debug(
                    f"knowledge_dataset_ensure_failed client_id={client_id} dataset={resolved} detail={ensure_exc}"
                )
            resolved_datasets.append(resolved)

        base_hash = sha256(normalized.encode()).hexdigest()[:12]
        datasets_hint = ",".join(resolved_datasets)
        top_k_label = k if k is not None else "default"
        logger.debug(
            f"knowledge_search_start client_id={client_id} rid={rid_value} query_hash={base_hash} "
            f"datasets={datasets_hint} top_k={top_k_label} global_unavailable={global_unavailable}"
        )

        queries = cls._expanded_queries(normalized)
        if len(queries) > 1:
            logger.debug(
                f"knowledge_search_expanded client_id={client_id} rid={rid_value} "
                f"variants={len(queries)} base_query_hash={base_hash}"
            )

        aggregated: list[KnowledgeSnippet] = []
        seen: set[str] = set()
        for variant in queries:
            snippets = await cls._search_single_query(
                variant,
                resolved_datasets,
                user,
                k,
                client_id,
                request_id=request_id,
            )
            if not snippets:
                continue
            for snippet in snippets:
                cleaned = snippet.text.strip()
                if not cleaned:
                    continue
                key = cleaned.casefold()
                if key in seen:
                    continue
                aggregated.append(snippet)
                seen.add(key)
                if k is not None and len(aggregated) >= k:
                    break
            if k is not None and len(aggregated) >= k:
                break

        if k is not None:
            return aggregated[:k]
        return aggregated

    @classmethod
    async def _search_single_query(
        cls,
        query: str,
        datasets: list[str],
        user: Any | None,
        k: int | None,
        client_id: int,
        *,
        request_id: str | None = None,
    ) -> list[KnowledgeSnippet]:
        if user is None:
            logger.warning(f"knowledge_search_skipped client_id={client_id}: user context unavailable")
            return []
        query_hash = sha256(query.encode()).hexdigest()[:12]
        skipped_aliases: list[str] = []
        rid_value = request_id or "na"

        async def _search_targets(targets: list[str]) -> list[str]:
            params: dict[str, Any] = {
                "datasets": targets,
                "user": cls._to_user_ctx(user),
            }
            if k is not None:
                params["top_k"] = k
            return await cognee.search(query, **params)

        ready_datasets: list[str] = []
        for dataset in datasets:
            alias = cls._alias_for_dataset(dataset)
            if alias in cls._PROJECTED_DATASETS:
                ready_datasets.append(dataset)
                continue
            try:
                if user is not None:
                    logger.info(f"knowledge_dataset_cognify_start dataset={alias} rid={rid_value}")
                ready = await cls._ensure_dataset_projected(dataset, user, timeout=2.0)
            except Exception as warm_exc:  # noqa: BLE001
                logger.debug(
                    f"knowledge_dataset_projection_warm_failed dataset={alias} rid={rid_value} detail={warm_exc}"
                )
                skipped_aliases.append(alias)
                continue
            if ready:
                ready_datasets.append(dataset)
                if user is not None:
                    logger.info(f"knowledge_dataset_cognify_ok dataset={alias} rid={rid_value}")
                continue
            if user is not None:
                logger.warning(
                    f"knowledge_dataset_search_skipped dataset={alias} rid={rid_value} reason=projection_pending"
                )
            skipped_aliases.append(alias)

        if not ready_datasets:
            if skipped_aliases:
                cls._log_once(
                    logging.DEBUG,
                    "search:skipped",
                    client_id=client_id,
                    rid=rid_value,
                    datasets=",".join(skipped_aliases),
                    min_interval=5.0,
                )
            fallback_raw = await cls._fallback_dataset_entries(datasets, user, top_k=k)
            if fallback_raw:
                primary_alias = skipped_aliases[0] if skipped_aliases else datasets[0]
                snippets = [
                    KnowledgeSnippet(text=value, dataset=primary_alias, kind="document")
                    for value in fallback_raw
                    if value.strip()
                ]
                return snippets[:k] if k is not None else snippets
            return []

        try:
            results = await _search_targets(ready_datasets)
            logger.debug(
                f"knowledge_search_ok client_id={client_id} rid={rid_value} "
                f"query_hash={query_hash} results={len(results)}"
            )
            if not results:
                await asyncio.sleep(0.25)
                retry = await _search_targets(ready_datasets)
                if retry:
                    logger.warning(
                        f"knowledge_search_retry_after_empty client_id={client_id} rid={rid_value} "
                        f"query_hash={query_hash} results={len(retry)}"
                    )
                    results = retry
            return await cls._build_snippets(results, ready_datasets, user)
        except (PermissionDeniedError, DatasetNotFoundError) as exc:
            logger.warning(
                f"knowledge_search_issue client_id={client_id} rid={rid_value} query_hash={query_hash} detail={exc}"
            )
            return []
        except Exception as exc:
            ready_aliases = [cls._alias_for_dataset(ds) for ds in ready_datasets]
            if cls._is_graph_missing_error(exc):
                for alias in ready_aliases:
                    cls._PROJECTED_DATASETS.discard(alias)
                logger.warning(
                    f"knowledge_dataset_search_skipped dataset={','.join(ready_aliases)} rid={rid_value} "
                    f"reason=projection_incomplete detail={exc}"
                )
                return []
            logger.warning(
                f"knowledge_search_failed client_id={client_id} rid={rid_value} query_hash={query_hash} detail={exc}"
            )
            return []

    @classmethod
    async def _build_snippets(
        cls,
        items: Iterable[Any],
        datasets: Sequence[str],
        user: Any | None,
    ) -> list[KnowledgeSnippet]:
        prepared: list[tuple[str, str, str | None, Mapping[str, Any] | None]] = []
        for raw in items:
            text, dataset_hint, metadata = cls._extract_search_item(raw)
            if not text:
                continue
            if metadata is not None and not isinstance(metadata, Mapping):
                metadata = cls._coerce_metadata(metadata)
            normalized_text = cls._normalize_text(text)
            if not normalized_text:
                continue
            prepared.append((text, normalized_text, dataset_hint, metadata))
        if not prepared:
            return []

        digests_sha = [cls._compute_digests(normalized_text) for _, normalized_text, _, _ in prepared]
        dataset_list = list(datasets)
        metadata_results: list[tuple[str | None, Mapping[str, Any] | None]] = [(None, None)] * len(prepared)
        pending: list[int] = []

        for index, ((_, _, dataset_hint, metadata), _) in enumerate(zip(prepared, digests_sha, strict=False)):
            if metadata is not None:
                meta_dict = dict(metadata)
                dataset_name = cls._dataset_from_metadata(meta_dict) or dataset_hint
                alias = cls._alias_for_dataset(dataset_name) if dataset_name else None
                if alias:
                    meta_dict.setdefault("dataset", alias)
                metadata_results[index] = (alias, meta_dict)
            else:
                metadata_results[index] = (dataset_hint, None)
                pending.append(index)

        if pending:
            lookups = await asyncio.gather(*(cls._collect_metadata(digests_sha[i], datasets) for i in pending))
            for slot, (dataset_name, meta) in zip(pending, lookups, strict=False):
                alias_source = dataset_name or prepared[slot][2]
                fallback_dataset = alias_source or (dataset_list[0] if dataset_list else "")
                alias = cls._alias_for_dataset(fallback_dataset) if fallback_dataset else None
                if meta:
                    meta_dict = dict(meta)
                else:
                    meta_dict = {}
                if alias:
                    meta_dict.setdefault("dataset", alias)
                metadata_results[slot] = (alias, meta_dict or None)

        snippets: list[KnowledgeSnippet] = []
        add_tasks: list[Awaitable[None]] = []
        for (text, normalized_text, dataset_hint, _), digest_sha, (resolved_dataset, payload) in zip(
            prepared, digests_sha, metadata_results, strict=False
        ):
            alias_source = resolved_dataset or dataset_hint or (dataset_list[0] if dataset_list else "")
            dataset_alias = cls._alias_for_dataset(alias_source) if alias_source else None
            if dataset_alias is None and dataset_list:
                dataset_alias = cls._alias_for_dataset(dataset_list[0])
            payload_dict: dict[str, Any]
            if payload:
                payload_dict = dict(payload)
            else:
                payload_dict = cls._infer_metadata_from_text(text) or {"kind": "document"}
            metadata_payload = cls._augment_metadata(
                payload_dict,
                dataset_alias,
                digest_sha=digest_sha,
            )
            if dataset_alias:
                add_tasks.append(HashStore.add(dataset_alias, digest_sha, metadata=metadata_payload))
            else:
                metadata_payload.pop("dataset", None)

            kind = cls._resolve_snippet_kind(metadata_payload, text)
            if kind == "message":
                continue

            dataset_value = str(metadata_payload.get("dataset") or dataset_alias or "").strip() or None
            if kind in {"document", "note"}:
                snippet_kind = cast(Literal["document", "note"], kind)
            else:
                snippet_kind = "unknown"
            snippets.append(KnowledgeSnippet(text=text, dataset=dataset_value, kind=snippet_kind))

        if add_tasks:
            await asyncio.gather(*add_tasks)
        return snippets

    @classmethod
    def _extract_search_item(
        cls,
        raw: Any,
    ) -> tuple[str, str | None, Mapping[str, Any] | None]:
        if raw is None:
            return "", None, None
        if is_dataclass(raw):
            return cls._extract_search_item(asdict(raw))
        if isinstance(raw, Mapping):
            text_value = raw.get("text", "")
            text = str(text_value or "").strip()
            metadata = cls._coerce_metadata(raw.get("metadata"))
            dataset_hint = cls._dataset_from_metadata(metadata)
            if dataset_hint is None:
                dataset_hint = cls._extract_dataset_key(raw)
            return text, dataset_hint, metadata
        text_attr = getattr(raw, "text", None)
        if text_attr is None and hasattr(raw, "content"):
            text_attr = getattr(raw, "content")
        text = str(text_attr or raw).strip()
        metadata = cls._coerce_metadata(getattr(raw, "metadata", None))
        dataset_hint = cls._dataset_from_metadata(metadata)
        if dataset_hint is None:
            dataset_hint = cls._extract_dataset_key(raw)
        return text, dataset_hint, metadata

    @staticmethod
    def _coerce_metadata(meta: Any) -> Mapping[str, Any] | None:
        if meta is None:
            return None
        if isinstance(meta, Mapping):
            return dict(meta)
        if is_dataclass(meta):
            return asdict(meta)
        try:
            return dict(meta)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _dataset_from_metadata(metadata: Mapping[str, Any] | None) -> str | None:
        if not metadata:
            return None
        for key in ("dataset", "dataset_name", "datasetId", "dataset_id"):
            value = metadata.get(key)
            if value not in (None, ""):
                return str(value)
        return None

    @staticmethod
    def _extract_dataset_key(source: Mapping[str, Any] | Any) -> str | None:
        if isinstance(source, Mapping):
            items = source.items()
        else:
            items = (
                (attr, getattr(source, attr, None)) for attr in ("dataset", "dataset_name", "datasetId", "dataset_id")
            )
        for key, value in items:
            if key in {"dataset", "dataset_name", "datasetId", "dataset_id"} and value not in (None, ""):
                return str(value)
        return None

    @classmethod
    async def _collect_metadata(
        cls,
        digest: str,
        datasets: Sequence[str],
    ) -> tuple[str | None, Mapping[str, Any] | None]:
        if not datasets:
            return None, None
        lookups = await asyncio.gather(
            *(HashStore.metadata(cls._alias_for_dataset(dataset), digest) for dataset in datasets)
        )
        for dataset, meta in zip(datasets, lookups, strict=False):
            alias = cls._alias_for_dataset(dataset)
            if meta:
                enriched = dict(meta)
                enriched.setdefault("dataset", alias)
                return alias, enriched
        fallback = cls._alias_for_dataset(datasets[0]) if datasets else None
        return fallback, None

    @staticmethod
    def _infer_metadata_from_text(text: str) -> dict[str, Any] | None:
        normalized = text.strip()
        if not normalized:
            return None
        lowered = normalized.casefold()
        for role in MessageRole:
            prefix = f"{role.value}:"
            if lowered.startswith(prefix.casefold()):
                return {"kind": "message", "role": role.value}
        return {"kind": "document"}

    @classmethod
    def _resolve_snippet_kind(
        cls, metadata: Mapping[str, Any] | None, text: str
    ) -> Literal[
        "document",
        "message",
        "note",
        "unknown",
    ]:
        if metadata:
            kind_value = str(metadata.get("kind", "")).lower()
            if kind_value in {"document", "note"}:
                return cast(Literal["document", "note"], kind_value)
            if kind_value == "message":
                return "message"
            if kind_value:
                return "unknown"
        inferred = cls._infer_metadata_from_text(text)
        if inferred and inferred.get("kind") == "message":
            return "message"
        return "document"

    @classmethod
    def _expanded_queries(cls, query: str) -> list[str]:
        return [query]

    @classmethod
    def _storage_root(cls) -> Path:
        root = CogneeConfig.storage_root()
        if root is not None:
            return root
        return Path(settings.COGNEE_STORAGE_PATH).expanduser().resolve()

    @classmethod
    async def _sanitize_hash_store(cls) -> None:
        md5_found_count = 0
        md5_converted_count = 0
        md5_removed_count = 0
        sha_final_count = 0

        all_aliases = await HashStore.list_all_datasets() if hasattr(HashStore, "list_all_datasets") else []
        for alias in all_aliases:
            digests_to_process = await HashStore.list(alias)
            for digest in digests_to_process:
                if len(digest) == 32:  # Likely an MD5 hash
                    md5_found_count += 1
                    metadata = await HashStore.metadata(alias, digest)
                    if metadata and metadata.get("text"):
                        content = str(metadata["text"])
                        sha256_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                        # Check if SHA256 already exists
                        if await HashStore.contains(alias, sha256_hash):
                            await HashStore.remove(alias, digest)
                            md5_removed_count += 1
                        else:
                            # Convert MD5 entry to SHA256
                            await HashStore.remove(alias, digest)
                            await HashStore.add(alias, sha256_hash, metadata)
                            md5_converted_count += 1
                    else:
                        # Cannot convert, remove stale MD5 entry
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

    @classmethod
    def _storage_path_for_sha(cls, digest_sha: str) -> Path | None:
        if len(digest_sha) != 64:
            cls._log_once(logging.WARNING, "storage_path_invalid_digest", sha=digest_sha)
            return None
        return cls._storage_root() / f"text_{digest_sha}.txt"

    @classmethod
    def _read_storage_text(
        cls,
        *,
        digest_sha: str,
    ) -> str | None:
        path = cls._storage_path_for_sha(digest_sha)
        if path is None:
            return None
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                cls._log_once(
                    logging.DEBUG,
                    "storage_read",
                    digest=digest_sha[:12],
                    detail=exc,
                    min_interval=60.0,
                )
        return None

    @staticmethod
    def _filename_to_digest(filename: str | None) -> str | None:
        if not filename:
            return None
        if filename.startswith("text_") and filename.endswith(".txt"):
            return filename[5:-4]
        return None

    @classmethod
    def _digest_from_raw_location(cls, raw_location: str | None) -> str | None:
        if not raw_location:
            return None
        try:
            parsed = urlparse(raw_location)
        except Exception:  # noqa: BLE001
            return None
        if parsed.scheme == "file":
            return cls._filename_to_digest(Path(parsed.path).name)
        return cls._filename_to_digest(Path(raw_location).name)

    @classmethod
    def _metadata_digest_sha(cls, metadata: Mapping[str, Any] | None) -> str | None:
        if not metadata:
            return None
        value = metadata.get("digest_sha")
        if isinstance(value, str):
            candidate = value.strip()
            if candidate:
                return candidate
        return None

    @classmethod
    def _prepare_dataset_row(cls, raw: Any, alias: str) -> DatasetRow:
        text_value = getattr(raw, "text", None)
        if not isinstance(text_value, str):
            if isinstance(text_value, (int, float, bool)):
                base_text = str(text_value)
            else:
                if text_value is not None:
                    cls._log_once(
                        level=logging.WARNING,
                        event="knowledge_dataset_row_skipped",
                        dataset=alias,
                        reason="non_string_text",
                        type=type(text_value).__name__,
                    )
                base_text = str(text_value or "")
        else:
            base_text = text_value
        metadata_obj = getattr(raw, "metadata", None)
        metadata_map = cls._coerce_metadata(metadata_obj)
        digest_sha_meta = cls._metadata_digest_sha(metadata_map)
        normalized_text = cls._normalize_text(base_text)
        if not normalized_text and digest_sha_meta:
            storage_text = cls._read_storage_text(digest_sha=digest_sha_meta)
            if storage_text is not None:
                normalized_text = cls._normalize_text(storage_text)
        metadata_dict: dict[str, Any] | None = dict(metadata_map) if metadata_map else None
        if metadata_dict is not None:
            metadata_dict.setdefault("dataset", alias)
        text_output = normalized_text if normalized_text else base_text
        if not normalized_text:
            cls._log_once(
                logging.WARNING,
                "knowledge_dataset_row_unrecoverable",
                dataset=alias,
                digest=digest_sha_meta[:12] if digest_sha_meta else "N/A",
                reason="empty_content",
            )
            state = cls._projection_state(alias)
            state["no_content_rows"] = state.get("no_content_rows", 0) + 1
        if normalized_text:
            digest_sha = cls._compute_digests(normalized_text)
            if metadata_dict is None:
                metadata_dict = {"dataset": alias}
            metadata_dict.setdefault("digest_sha", digest_sha)
        if metadata_dict and not metadata_dict.get("dataset"):
            metadata_dict["dataset"] = alias
        if metadata_dict is not None and not metadata_dict:
            metadata_dict = None
        return DatasetRow(text=text_output, metadata=metadata_dict)

    @classmethod
    def _normalize_text(cls, text: Any) -> str:
        if not isinstance(text, str):
            text = str(text) if text is not None else ""
        return normalize_text(text)

    @classmethod
    def _augment_metadata(
        cls,
        metadata: Mapping[str, Any] | None,
        dataset_alias: str | None,
        *,
        digest_sha: str,
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

    @staticmethod
    def _compute_digests(normalized_text: str) -> str:
        payload = normalized_text.encode("utf-8")
        digest_sha = sha256(payload).hexdigest()
        return digest_sha

    @classmethod
    async def _heal_dataset_storage(
        cls,
        dataset: str,
        user: Any | None,
        *,
        entries: Sequence[DatasetRow] | None = None,
        reason: str,
    ) -> tuple[int, int]:
        alias = cls._alias_for_dataset(dataset)
        if entries is None:
            try:
                fetched = await cls._list_dataset_entries(alias, user)
            except Exception as exc:  # noqa: BLE001 - diagnostics only
                logger.debug(f"knowledge_dataset_heal_fetch_failed dataset={alias} reason={reason} detail={exc}")
                return 0, 0
            entries = fetched
        missing = 0
        healed = 0
        add_tasks: list[Awaitable[None]] = []
        for entry in entries:
            normalized = cls._normalize_text(entry.text)
            metadata_map = entry.metadata if isinstance(entry.metadata, Mapping) else None
            digest_sha_meta = cls._metadata_digest_sha(metadata_map)
            if not normalized:
                cls._log_once(
                    logging.WARNING,
                    "knowledge_dataset_heal_unrecoverable",
                    dataset=alias,
                    digest=digest_sha_meta[:12] if digest_sha_meta else "N/A",
                    reason="empty_content",
                )
                continue
            digest_sha = cls._compute_digests(normalized)
            storage_path = cls._storage_path_for_sha(digest_sha)
            if storage_path is None:
                continue
            sha_exists = storage_path.exists()
            if not sha_exists:
                missing += 1
            _, created = cls._ensure_storage_file(
                digest_sha=digest_sha,
                text=normalized,
                dataset=alias,
            )
            if created:
                healed += 1
            metadata_payload = cls._augment_metadata(entry.metadata, alias, digest_sha=digest_sha)
            add_tasks.append(HashStore.add(alias, digest_sha, metadata=metadata_payload))
        if add_tasks:
            await asyncio.gather(*add_tasks)
        if missing or healed:
            logger.debug(
                f"knowledge_dataset_storage_heal dataset={alias} reason={reason} missing={missing} healed={healed}"
            )
            cls._log_storage_state(alias, missing_count=missing, healed_count=healed)
            state = cls._projection_state(alias)
            state["healed_count"] = state.get("healed_count", 0) + healed
        return missing, healed

    @classmethod
    async def _rebuild_from_disk(cls, alias: str) -> tuple[int, int]:
        """Synchronise HashStore with files present on disk for the dataset."""
        storage_root = cls._storage_root()
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
                    cls._log_once(logging.INFO, "rebuild_disk_md5_ignored", path=path.name)
                continue
            digest_sha_from_name = digest_match.group(1)
            try:
                contents = path.read_text(encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    f"knowledge_rebuild_read_failed dataset={alias} sha={digest_sha_from_name[:12]} detail={exc}"
                )
                unreadable_count += 1
                continue
            normalized = cls._normalize_text(contents)
            if not normalized:
                empty_count += 1
                continue
            digest_sha_from_content = cls._compute_digests(normalized)
            if digest_sha_from_content != digest_sha_from_name:
                logger.warning(
                    f"knowledge_rebuild_digest_mismatch dataset={alias} "
                    f"path_sha={digest_sha_from_name[:12]} content_sha={digest_sha_from_content[:12]}"
                )
                mismatch_count += 1
                continue
            inferred_kind = cls._resolve_snippet_kind({"kind": "document"}, normalized)
            metadata = cls._augment_metadata(
                {"kind": inferred_kind},
                alias,
                digest_sha=digest_sha_from_content,
            )
            try:
                already = await HashStore.contains(alias, digest_sha_from_content)
                await HashStore.add(alias, digest_sha_from_content, metadata=metadata)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    f"knowledge_rebuild_hashstore_failed dataset={alias} sha={digest_sha_from_content[:12]} detail={exc}"
                )
                continue
            linked += 1
            if not already:
                created += 1
        if created > 0 or linked > 0 or mismatch_count > 0 or unreadable_count > 0 or empty_count > 0:
            logger.debug(
                f"[disk_rebuild_commit] dataset={alias} created={created} linked={linked} sha_only=True "
                f"mismatch_count={mismatch_count} unreadable_count={unreadable_count} empty_count={empty_count}"
            )
        return created, linked

    @classmethod
    async def _reingest_from_hashstore(
        cls,
        alias: str,
        user: Any | None,
        digests: Sequence[tuple[str, Mapping[str, Any] | None]],
    ) -> tuple[int, int, str | None]:
        """Reinsert documents from stored digests back into Cognee when graph rows are absent."""
        if not digests:
            return 0, 0, None
        reinserted = 0
        healed_count = 0
        last_dataset: str | None = None
        for digest_sha, metadata in digests:
            if len(digest_sha) != 64:
                logger.warning("hashstore_legacy_digest_skipped digest=%s", digest_sha[:12])
                continue
            path = cls._storage_path_for_sha(digest_sha)
            if path is None:
                continue
            logger.debug(f"[reingest_probe] sha={digest_sha} path_attempt={path}")
            normalized = None
            if path.exists():
                try:
                    raw_text = path.read_text(encoding="utf-8")
                    normalized = cls._normalize_text(raw_text)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(f"knowledge_reingest_read_failed dataset={alias} sha={digest_sha[:12]} detail={exc}")

            # Healing step: if file is missing but content is in metadata, re-create it
            if not normalized and metadata and metadata.get("text"):
                normalized = cls._normalize_text(str(metadata["text"]))
                if normalized:
                    cls._ensure_storage_file(digest_sha=digest_sha, text=normalized, dataset=alias)
                    healed_count += 1
            elif not normalized and not metadata:  # If file is missing and no metadata to heal from
                if await HashStore.contains(alias, digest_sha):
                    await HashStore.remove(alias, digest_sha)
                    cls._log_once(
                        logging.WARNING,
                        "knowledge_reingest_stale_md5_removed",
                        dataset=alias,
                        digest_sha=digest_sha[:12],
                        reason="no_metadata_to_heal",
                    )
                continue

            if not normalized:
                cls._log_once(
                    logging.WARNING,
                    "knowledge_reingest_unrecoverable",
                    dataset=alias,
                    digest_sha=digest_sha[:12],
                )
                continue

            kind = metadata.get("kind") if isinstance(metadata, Mapping) else None
            if kind == "message":
                continue
            meta_payload = metadata if isinstance(metadata, Mapping) else None
            try:
                dataset_name, created = await cls.update_dataset(
                    normalized,
                    alias,
                    user,
                    node_set=None,
                    metadata=meta_payload,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"knowledge_reingest_failed dataset={alias} digest_sha={digest_sha[:12]} detail={exc}")
                continue
            if created:
                reinserted += 1
                cls._register_dataset_identifier(alias, dataset_name)
                last_dataset = dataset_name
        return reinserted, healed_count, last_dataset

    @classmethod
    def _ensure_storage_file(
        cls,
        *,
        digest_sha: str,
        text: str,
        dataset: str | None = None,
    ) -> tuple[Path | None, bool]:
        path = cls._storage_path_for_sha(digest_sha)
        if path is None:
            return None, False

        if path.exists():
            # ensure md5 mirror even if SHA exists
            try:
                from hashlib import md5 as _md5

                md5_hex = _md5(text.encode("utf-8")).hexdigest()
                md5_path = path.parent / f"text_{md5_hex}.txt"
                if not md5_path.exists():
                    try:
                        md5_path.symlink_to(path.name)  # relative link inside same dir
                        logger.debug(f"md5_mirror_link_created md5={md5_hex[:12]} -> {path.name[:16]}")
                    except Exception:
                        if not md5_path.exists():  # возможно, другой поток уже создал
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

            # create md5 mirror for Cognee (symlink or copy)
            try:
                from hashlib import md5 as _md5

                md5_hex = _md5(text.encode("utf-8")).hexdigest()
                md5_path = path.parent / f"text_{md5_hex}.txt"
                if not md5_path.exists():
                    try:
                        md5_path.symlink_to(path.name)
                        logger.debug(f"md5_mirror_link_created md5={md5_hex[:12]} -> {path.name[:16]}")
                    except Exception:
                        if not md5_path.exists():  # возможно, другой поток уже создал
                            md5_path.write_text(text, encoding="utf-8")
                            logger.debug(
                                f"md5_mirror_file_created md5={md5_hex[:12]} bytes={len(text.encode('utf-8'))}"
                            )
            except Exception as md5_exc:
                logger.debug(f"md5_mirror_skip reason={md5_exc}")

            logger.debug(f"kb_storage ensure sha={digest_sha[:12]} created=True")
            return path, True

        except Exception as exc:  # noqa: BLE001 - log and proceed with Cognee handling
            logger.warning(
                f"knowledge_storage_write_failed digest_sha={digest_sha[:12]} "
                f"dataset={dataset or 'unknown'} path={path} detail={exc}"
            )
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
            return None, False

    @classmethod
    async def add_text(
        cls,
        text: str,
        *,
        dataset: str | None = None,
        node_set: list[str] | None = None,
        client_id: int | None = None,
        role: MessageRole | None = None,
        metadata: Mapping[str, Any] | None = None,
        project: bool = True,
    ) -> None:
        """Add message text to a dataset, schedule cognify if new."""
        user = await cls._get_cognee_user()
        ds = dataset or (cls._dataset_name(client_id) if client_id is not None else cls.GLOBAL_DATASET)
        meta_payload: dict[str, Any] = {}
        if metadata:
            meta_payload.update(dict(metadata))

        if role:
            text = f"{role.value}: {text}"
            meta_payload.setdefault("kind", "message")
            meta_payload.setdefault("role", role.value)
        else:
            meta_payload.setdefault("kind", "document")

        normalized_text = cls._normalize_text(text)
        if not normalized_text.strip():
            logger.debug(f"empty_content_filtered dataset={ds} role={role.value if role else 'document'}")
            return

        target_alias = cls._resolve_dataset_alias(ds)
        meta_payload.setdefault("dataset", target_alias)

        digest_sha = cls._compute_digests(normalized_text)

        attempts = 0
        role_label = role.value if role else "document"
        while attempts < 2:
            try:
                logger.debug(f"kb_append start dataset={target_alias} role={role_label} length={len(normalized_text)}")
                resolved_name, created = await cls.update_dataset(
                    normalized_text,
                    target_alias,
                    user,
                    node_set=list(node_set or []),
                    metadata=meta_payload,
                )
                if created:
                    alias = cls._alias_for_dataset(target_alias)
                    if not project or cls._is_chat_dataset(alias):
                        pending = cls._queue_chat_dataset(alias)
                        logger.debug(f"kb_chat_ingest queued={pending} dataset={alias}")
                        cls._ensure_chat_projection_task(alias)
                    else:
                        task = asyncio.create_task(cls._process_dataset(resolved_name, user))
                        task.add_done_callback(cls._log_task_exception)
                return
            except PermissionDeniedError:
                raise
            except FileNotFoundError as exc:
                logger.debug(f"kb_append storage_missing dataset={target_alias} sha={digest_sha[:12]} detail={exc}")
                cls._ensure_storage_file(digest_sha=digest_sha, text=normalized_text, dataset=target_alias)
                await HashStore.clear(target_alias)
                cls._PROJECTED_DATASETS.discard(cls._alias_for_dataset(target_alias))
                rebuilt = await cls.rebuild_dataset(target_alias, user)
                if not rebuilt:
                    logger.info(f"kb_append rebuild_failed dataset={target_alias}")
                    break
                attempts += 1
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"kb_append skipped dataset={target_alias}: {exc}", exc_info=True)
                break
        logger.info(f"kb_append aborted dataset={target_alias}")

    @classmethod
    async def save_client_message(cls, text: str, client_id: int) -> None:
        await cls.add_text(
            text,
            dataset=cls._chat_dataset_name(client_id),
            client_id=client_id,
            role=MessageRole.CLIENT,
            node_set=[f"client:{client_id}", "chat_message"],
            metadata={"channel": "chat"},
            project=False,
        )

    @classmethod
    async def save_ai_message(cls, text: str, client_id: int) -> None:
        await cls.add_text(
            text,
            dataset=cls._chat_dataset_name(client_id),
            client_id=client_id,
            role=MessageRole.AI_COACH,
            node_set=[f"client:{client_id}", "chat_message"],
            metadata={"channel": "chat"},
            project=False,
        )

    @classmethod
    async def get_message_history(cls, client_id: int, limit: int | None = None) -> list[str]:
        """Return recent chat messages for a client."""
        dataset: str = cls._resolve_dataset_alias(cls._chat_dataset_name(client_id))
        user: Any | None = await cls._get_cognee_user()
        if user is None:
            if not cls._warned_missing_user:
                logger.warning(f"History fetch skipped client_id={client_id}: default user unavailable")
                cls._warned_missing_user = True
            else:
                logger.debug(f"History fetch skipped client_id={client_id}: default user unavailable")
            return []
        try:
            await cls._ensure_dataset_exists(dataset, user)
        except Exception as exc:  # pragma: no cover - non-critical indexing failure
            logger.debug(f"Dataset ensure skipped client_id={client_id}: {exc}")
        datasets_module = getattr(cognee, "datasets", None)
        if datasets_module is None:
            if cls._has_datasets_module is not False:
                logger.warning(f"History fetch skipped client_id={client_id}: datasets module unavailable")
            cls._has_datasets_module = False
            return []

        list_data = getattr(datasets_module, "list_data", None)
        if not callable(list_data):
            if cls._has_datasets_module is not False:
                logger.warning(
                    f"History fetch skipped client_id={client_id}: list_data callable missing",
                )
            cls._has_datasets_module = False
            return []

        cls._has_datasets_module = True
        list_data_callable = cast(Callable[..., Awaitable[Iterable[Any]]], list_data)
        user_ctx: Any | None = cls._to_user_ctx(user)
        try:
            data = await cls._fetch_dataset_rows(list_data_callable, dataset, user)
        except Exception:
            logger.info(f"No message history found for client_id={client_id}")
            return []
        messages: list[str] = []
        for item in data:
            text = getattr(item, "text", None)
            if text:
                messages.append(str(text))
        limit = limit or settings.CHAT_HISTORY_LIMIT
        return messages[-limit:]

    @classmethod
    async def _get_cognee_user(cls) -> Any | None:
        """Fetch and cache default Cognee user."""
        if cls._user is not None:
            return cls._user
        try:
            cls._user = await get_default_user()
        except Exception:
            cls._user = None
        return cls._user

    @classmethod
    def _resolve_dataset_alias(cls, name: str) -> str:
        """Map dataset alias to the canonical dataset identifier."""
        normalized = name.strip()
        if not normalized:
            return name
        if normalized.startswith(cls._CLIENT_ALIAS_PREFIX):
            suffix = normalized[len(cls._CLIENT_ALIAS_PREFIX) :]
            try:
                client_id = int(suffix)
            except ValueError:
                return normalized
            return cls._dataset_name(client_id)
        if normalized.startswith(cls._LEGACY_CLIENT_PREFIX):
            suffix = normalized[len(cls._LEGACY_CLIENT_PREFIX) :]
            try:
                client_id = int(suffix)
            except ValueError:
                return normalized
            return cls._dataset_name(client_id)
        return normalized

    @classmethod
    def _alias_for_dataset(cls, dataset: str) -> str:
        stripped = dataset.strip()
        if stripped in cls._DATASET_ALIASES:
            return cls._DATASET_ALIASES[stripped]
        return cls._resolve_dataset_alias(stripped)

    @classmethod
    def _register_dataset_identifier(cls, alias: str, identifier: str) -> None:
        canonical = cls._resolve_dataset_alias(alias)
        if not canonical:
            return
        cls._DATASET_IDS[canonical] = identifier
        cls._DATASET_ALIASES[identifier] = canonical

    @staticmethod
    def _looks_like_uuid(value: str) -> bool:
        try:
            UUID(value)
        except (ValueError, TypeError):
            return False
        return True

    @classmethod
    def _log_once(cls, level: int, event: str, **fields) -> None:
        """Log a message with throttling to avoid flooding."""
        now = time.time()
        min_interval = float(cast(float, fields.pop("min_interval", 10.0)))
        throttle_key = fields.pop("throttle_key", event)

        last_log_time = cls._LOG_THROTTLE.get(throttle_key, 0.0)

        if now - last_log_time >= min_interval:
            message_parts = [event]
            for key, value in fields.items():
                if value is not None:
                    # Format value safely, handling dataclasses and other objects
                    if is_dataclass(value):
                        value_str = str(asdict(value))
                    else:
                        value_str = str(value)
                    # Simple quoting for values with spaces
                    if " " in value_str and not (value_str.startswith("'") or value_str.startswith('"')):
                        value_str = f'"{value_str}"'
                    message_parts.append(f"{key}={value_str}")

            full_message = " ".join(message_parts)

            # Use loguru's level-based logging methods for better context
            logger.log(level, full_message)
            cls._LOG_THROTTLE[throttle_key] = now

    @classmethod
    def _projection_state(cls, alias: str) -> dict[str, Any]:
        return cls._PROJECTION_STATE.setdefault(
            alias,
            {
                "status": "unknown",
                "reason": None,
                "next_check_ts": 0.0,
                "processing": False,
            },
        )

    @classmethod
    async def _get_dataset_id(cls, dataset: str, user: Any | None) -> str | None:
        alias = cls._alias_for_dataset(dataset)
        if cls._looks_like_uuid(dataset):
            cls._register_dataset_identifier(alias, dataset)
            if dataset:
                cls._log_once(logging.DEBUG, "dataset_resolved", name=alias, id=dataset, min_interval=10.0)
            return dataset

        identifier = cls._DATASET_IDS.get(alias)
        if identifier:
            cls._log_once(logging.DEBUG, "dataset_resolved", name=alias, id=identifier, min_interval=10.0)
            return identifier

        if user is not None:
            try:
                await cls._ensure_dataset_exists(alias, user)
                identifier = cls._DATASET_IDS.get(alias)
                if identifier:
                    cls._log_once(logging.DEBUG, "dataset_resolved", name=alias, id=identifier, min_interval=5.0)
                    return identifier
            except Exception as exc:  # noqa: BLE001 - diagnostics only
                logger.debug(f"knowledge_dataset_id_lookup_failed dataset={alias} detail={exc}")

        if user is not None:
            metadata = await cls._get_dataset_metadata(alias, user)
            if metadata is not None:
                identifier = cls._extract_dataset_identifier(metadata)
                if identifier:
                    cls._register_dataset_identifier(alias, identifier)
                    cls._log_once(
                        logging.DEBUG,
                        "dataset_resolved",
                        name=alias,
                        id=identifier,
                        min_interval=5.0,
                    )
                    return identifier
        return None

    @classmethod
    def _extract_dataset_identifier(cls, info: Any | None) -> str | None:
        if info is None:
            return None
        candidates: list[Any] = []
        if isinstance(info, dict):
            for key in cls._DATASET_IDENTIFIER_FIELDS:
                if key in info:
                    candidates.append(info[key])
        for key in cls._DATASET_IDENTIFIER_FIELDS:
            value = getattr(info, key, None)
            if value is not None:
                candidates.append(value)
        for candidate in candidates:
            if candidate in (None, ""):
                continue
            text = candidate if isinstance(candidate, str) else str(candidate)
            try:
                identifier = str(UUID(text))
            except (ValueError, TypeError):
                continue
            return identifier
        return None

    @classmethod
    async def _ensure_dataset_exists(cls, name: str, user: Any | None) -> None:
        """Create dataset if it does not exist for the given user."""
        user_id = cls._to_user_id(user)
        if user_id is None:
            logger.debug(f"Dataset ensure skipped dataset={name}: user context unavailable")
            return
        canonical = cls._resolve_dataset_alias(name)
        try:
            from cognee.modules.data.methods import get_authorized_dataset_by_name, create_authorized_dataset  # noqa
        except Exception:
            return
        exists = await get_authorized_dataset_by_name(
            canonical, cls._to_user_ctx(user), "write"
        )  # pyrefly: ignore[bad-argument-type]
        if exists is not None:
            identifier = cls._extract_dataset_identifier(exists)
            if identifier:
                cls._register_dataset_identifier(canonical, identifier)
            return
        created = await create_authorized_dataset(
            canonical, cls._to_user_ctx(user)
        )  # pyrefly: ignore[bad-argument-type]
        identifier = cls._extract_dataset_identifier(created)
        if identifier:
            cls._register_dataset_identifier(canonical, identifier)

    @classmethod
    async def _ensure_dataset_projected(cls, dataset: str, user: Any | None, *, timeout: float = 2.0) -> bool:
        alias = cls._alias_for_dataset(dataset)

        status = await cls._wait_for_projection(dataset, user=user, timeout_s=timeout)
        if status == ProjectionStatus.READY:
            cls._PROJECTED_DATASETS.add(alias)
            return True

        # Не готово — пробуем прогнать cognify, затем ждём ещё раз
        try:
            logger.debug(f"knowledge_dataset_cognify_start dataset={alias}")
            await cls._process_dataset(dataset, user)
            logger.debug(f"knowledge_dataset_cognify_ok dataset={alias}")
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"knowledge_dataset_projection_warm_failed dataset={alias} detail={exc}")
            return False

        status = await cls._wait_for_projection(dataset, user=user, timeout_s=timeout)
        if status == ProjectionStatus.READY:
            cls._PROJECTED_DATASETS.add(alias)
            return True
        return False

    @classmethod
    def _dataset_name(cls, client_id: int) -> str:
        """Generate canonical dataset alias for a client profile."""
        return f"{cls._CLIENT_ALIAS_PREFIX}{client_id}"

    @classmethod
    def _chat_dataset_name(cls, client_id: int) -> str:
        return f"{cls._CHAT_ALIAS_PREFIX}{client_id}"

    @classmethod
    def _is_chat_dataset(cls, dataset: str) -> bool:
        alias = cls._alias_for_dataset(dataset)
        return alias.startswith(cls._CHAT_ALIAS_PREFIX)

    @classmethod
    def _queue_chat_dataset(cls, alias: str) -> int:
        normalized = cls._alias_for_dataset(alias)
        pending = cls._CHAT_PENDING.get(normalized, 0) + 1
        cls._CHAT_PENDING[normalized] = pending
        return pending

    @classmethod
    def _chat_debounce_seconds(cls) -> float:
        raw_minutes = float(settings.KB_CHAT_PROJECT_DEBOUNCE_MIN)
        return max(raw_minutes, 0.0) * 60.0

    @classmethod
    def _chat_projection_delay(cls, alias: str) -> float:
        debounce = cls._chat_debounce_seconds()
        if debounce <= 0:
            return 0.0
        last = cls._CHAT_LAST_PROJECT_TS.get(alias, 0.0)
        now = monotonic()
        if last <= 0:
            return 0.0
        remaining = (last + debounce) - now
        return remaining if remaining > 0 else 0.0

    @classmethod
    def _ensure_chat_projection_task(cls, alias: str) -> None:
        normalized = cls._alias_for_dataset(alias)
        if cls._CHAT_PENDING.get(normalized, 0) <= 0:
            return
        existing = cls._CHAT_PROJECT_TASKS.get(normalized)
        if existing and not existing.done():
            return
        delay = cls._chat_projection_delay(normalized)
        task = asyncio.create_task(cls._run_chat_projection(normalized, delay))
        cls._CHAT_PROJECT_TASKS[normalized] = task
        task.add_done_callback(cls._log_task_exception)

    @classmethod
    async def _run_chat_projection(cls, alias: str, delay: float) -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        queued = cls._CHAT_PENDING.get(alias, 0)
        if queued <= 0:
            cls._CHAT_PROJECT_TASKS.pop(alias, None)
            return
        logger.debug(f"kb_chat_project start queued={queued} dataset={alias}")
        user = await cls._get_cognee_user()
        started = monotonic()
        try:
            await cls._process_dataset(alias, user)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"kb_chat_project failed dataset={alias} queued={queued} detail={exc}")
            cls._CHAT_PROJECT_TASKS.pop(alias, None)
            cls._CHAT_LAST_PROJECT_TS[alias] = monotonic()
            cls._ensure_chat_projection_task(alias)
            return
        took_ms = int((monotonic() - started) * 1000)
        logger.debug(f"kb_chat_project end queued={queued} dataset={alias} took_ms={took_ms}")
        cls._CHAT_PENDING.pop(alias, None)
        cls._CHAT_PROJECT_TASKS.pop(alias, None)
        cls._CHAT_LAST_PROJECT_TS[alias] = monotonic()

    @classmethod
    def _describe_list_data(cls, list_data: Callable[..., Awaitable[Iterable[Any]]]) -> tuple[bool | None, bool | None]:
        try:
            signature = inspect.signature(list_data)
        except (TypeError, ValueError):
            return None, None
        parameter = signature.parameters.get("user")
        if parameter is None:
            return False, False
        supports_keyword = parameter.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
        requires_user = parameter.default is inspect._empty
        return supports_keyword, requires_user

    @classmethod
    async def _fetch_dataset_rows(
        cls,
        list_data: Callable[..., Awaitable[Iterable[Any]]],
        dataset: str,
        user: Any | None,
    ) -> list[Any]:
        """Fetch dataset rows, gracefully handling legacy signatures."""
        alias = cls._alias_for_dataset(dataset)
        user_ctx = cls._to_user_ctx(user)
        dataset_id = await cls._get_dataset_id(dataset, user)
        if dataset_id is None:
            cls._log_once(
                logging.WARNING,
                "projection:dataset_id_unavailable",
                dataset=alias,
                reason="dataset_id_unavailable",
            )
            raise ProjectionProbeError(f"dataset_id_unavailable alias={alias}")

        if user_ctx is not None:
            if cls._list_data_supports_user is None or cls._list_data_requires_user is None:
                supports, requires = cls._describe_list_data(list_data)
                if supports is not None:
                    cls._list_data_supports_user = supports
                if requires is not None:
                    cls._list_data_requires_user = requires

        if user_ctx is not None and cls._list_data_supports_user is not False:
            try:
                rows = await list_data(dataset_id, user=user_ctx)
            except TypeError:
                logger.debug("cognee.datasets.list_data rejected keyword 'user', retrying without keyword")
                cls._list_data_supports_user = False
                if cls._list_data_requires_user:
                    logger.debug("cognee.datasets.list_data requires user context, retrying positional call")
                    rows = await list_data(dataset_id, user_ctx)
                    cls._list_data_supports_user = True
                    return list(rows)
            else:
                cls._list_data_supports_user = True
                return list(rows)

        if user_ctx is not None and cls._list_data_requires_user:
            rows = await list_data(dataset_id, user_ctx)
            cls._list_data_supports_user = True
            return list(rows)

        try:
            rows = await list_data(dataset_id)
        except TypeError as exc:
            if user_ctx is not None:
                logger.debug(
                    f"cognee.datasets.list_data raised {exc.__class__.__name__}: retrying with positional user"
                )
                rows = await list_data(dataset_id, user_ctx)
                cls._list_data_supports_user = True
                cls._list_data_requires_user = True
                return list(rows)
            raise
        return list(rows)

    @staticmethod
    def _client_profile_text(client: Client) -> str:
        """Format client profile attributes into text for indexing."""
        parts = []
        if client.name:
            parts.append(f"name: {client.name}")
        if client.gender:
            parts.append(f"gender: {client.gender}")
        if client.born_in:
            parts.append(f"born_in: {client.born_in}")
        if client.weight:
            parts.append(f"weight: {client.weight}")
        if client.workout_experience:
            parts.append(f"workout_experience: {client.workout_experience}")
        if client.workout_goals:
            parts.append(f"workout_goals: {client.workout_goals}")
        if client.health_notes:
            parts.append(f"health_notes: {client.health_notes}")
        return "profile: " + "; ".join(parts)

    @classmethod
    async def _ensure_profile_indexed(cls, client_id: int, user: Any | None) -> None:
        """Fetch client profile and add it to dataset if missing."""
        try:
            client = await APIService.profile.get_client(client_id)
        except UserServiceError as e:
            logger.warning(f"Failed to fetch client id={client_id}: {e}")
            return
        if not client:
            return
        text = cls._client_profile_text(client)
        dataset = cls._dataset_name(client_id)
        dataset, created = await cls.update_dataset(
            text,
            dataset,
            user,
            node_set=["client_profile"],
            metadata={"kind": "document", "source": "client_profile"},
        )
        if created:
            await cls._process_dataset(dataset, user)

    @classmethod
    async def _process_dataset(cls, dataset: str, user: Any | None) -> None:
        """Run cognify on a dataset with a per-dataset lock."""
        lock = cls._cognify_locks.get(dataset)
        async with lock:
            alias = cls._alias_for_dataset(dataset)
            user_ctx = cls._to_user_ctx(user)
            try:
                dataset_id = await cls._get_dataset_id(alias, user)
            except ProjectionProbeError:
                dataset_id = None
            cls._log_once(
                logging.DEBUG,
                "projection:process",
                dataset=alias,
                dataset_id=dataset_id,
                min_interval=5.0,
            )
            await cls._project_dataset(alias, user, allow_rebuild=True)

    @staticmethod
    def _log_task_exception(task: asyncio.Task[Any]) -> None:
        """Log exception from a background task."""
        if exc := task.exception():
            logger.warning(f"Dataset processing failed: {exc}", exc_info=True)

    @classmethod
    def _to_user_or_none(cls, user: Any | None) -> Any | None:
        """Temporary alias for backward compatibility."""
        return cls._to_user_ctx(user)

    @classmethod
    def _to_user_ctx(cls, user: Any | None) -> Any | None:
        """Normalize user object into SimpleNamespace or return None for Cognee API calls."""
        if user is None:
            return None
        if isinstance(user, CogneeUser):
            return SimpleNamespace(**asdict(user))
        if is_dataclass(user) and hasattr(user, "id"):
            return SimpleNamespace(**asdict(user))
        if hasattr(user, "id"):
            return user
        return None

    @classmethod
    def _to_user_id(cls, user: Any | None) -> str | None:
        """Normalize user object into a string identifier for internal keys/logs or return None."""
        user_id: str | None = None
        kind: str = "unknown"

        if user is None:
            kind = "None"
        elif isinstance(user, CogneeUser):
            user_id = str(user.id)
            kind = "CogneeUser"
        elif is_dataclass(user):
            d = asdict(user)
            if d.get("id"):
                user_id = str(d["id"])
                kind = "dataclass"
            else:
                kind = "dataclass_no_id"
        elif getattr(user, "id", None):
            user_id = str(user.id)
            kind = "has_id_attr"

        cls._log_once(
            logging.DEBUG,
            "kb_user_id_startup",
            kind=kind,
            value=user_id or "None",
            min_interval=3600.0,  # Log once per hour
        )
        return user_id

    @classmethod
    def _is_graph_missing_error(cls, exc: Exception) -> bool:
        message = str(exc)
        if "Empty graph" in message or "empty graph" in message:
            return True
        if "EntityNotFound" in exc.__class__.__name__:
            return True
        status = getattr(exc, "status_code", None)
        return status == 404

    @classmethod
    async def _warm_up_datasets(cls, datasets: list[str], user: Any | None) -> None:
        """Ensure datasets are cognified before retrying a search."""
        for dataset in datasets:
            try:
                await cls._process_dataset(dataset, user)
            except Exception as exc:  # noqa: BLE001 - logging context is sufficient here
                logger.warning(f"knowledge_dataset_warmup_failed dataset={dataset} detail={exc}")

    @classmethod
    async def _project_dataset(
        cls,
        dataset: str,
        user: Any | None,
        *,
        allow_rebuild: bool = True,
    ) -> None:
        """Run cognify and wait for the dataset projection to become available."""
        alias = cls._alias_for_dataset(dataset)
        user_ctx = cls._to_user_ctx(user)
        dataset_id = await cls._get_dataset_id(alias, user)
        target = dataset_id or alias
        if user_ctx is None:
            logger.warning(f"knowledge_project_skipped dataset={alias}: user context unavailable")
            return
        cls._log_once(
            logging.DEBUG,
            "projection:cognify_start",
            dataset=alias,
            dataset_id=dataset_id,
            min_interval=5.0,
        )
        try:
            await cognee.cognify(datasets=[target], user=user_ctx)  # pyrefly: ignore[bad-argument-type]
        except FileNotFoundError as exc:
            missing_path = getattr(exc, "filename", None) or str(exc)
            logger.debug(f"knowledge_dataset_storage_missing dataset={alias} missing={missing_path}")
            missing, healed = await cls._heal_dataset_storage(alias, user, reason="cognify_missing")
            cls._PROJECTED_DATASETS.discard(alias)
            if healed > 0:
                await cls._project_dataset(alias, user, allow_rebuild=True)
                return
            cls._log_once(
                logging.WARNING,
                "storage_missing:heal_failed",
                dataset=alias,
                missing=missing,
                healed=healed,
                min_interval=30.0,
            )
            cls._log_storage_state(alias, missing_count=missing, healed_count=healed)
            if await cls.rebuild_dataset(alias, user):
                logger.info(f"knowledge_dataset_rebuilt dataset={alias}")
                await cls._project_dataset(alias, user, allow_rebuild=True)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"knowledge_dataset_cognify_failed dataset={dataset} detail={exc}")
            raise
        cls._log_once(
            logging.DEBUG,
            "projection:cognify_done",
            dataset=alias,
            dataset_id=dataset_id,
            min_interval=5.0,
        )
        status = await cls._wait_for_projection(alias, user=user)
        if status == ProjectionStatus.READY:
            projected = True
        else:
            projected = False
        if not projected:
            logger.debug(f"knowledge_dataset_projection_pending dataset={alias} result=timeout")

    @classmethod
    async def rebuild_dataset(cls, dataset: str, user: Any | None, sha_only: bool = False) -> "RebuildResult":
        """Rebuild dataset content by re-adding raw entries and clearing hash store."""
        alias = cls._alias_for_dataset(dataset)
        reinserted = 0
        healed_count = 0
        linked_from_disk = 0
        rehydrated = 0

        try:
            await cls._ensure_dataset_exists(alias, user)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"knowledge_dataset_rebuild_ensure_failed dataset={alias} detail={exc}")
        await cls._heal_dataset_storage(alias, user, reason="rebuild_preflight")
        await HashStore.clear(alias)
        cls._PROJECTED_DATASETS.discard(alias)
        await cls._heal_dataset_storage(alias, user, reason="rebuild_preflight")
        try:
            entries = await cls._list_dataset_entries(alias, user)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"knowledge_dataset_rebuild_list_failed dataset={alias} detail={exc}")
            return RebuildResult()
        last_dataset: str | None = None
        if not entries:
            created_from_disk, linked_from_disk = await cls._rebuild_from_disk(alias)
            if linked_from_disk:
                logger.debug(
                    f"knowledge_dataset_rebuild_disk_sync dataset={alias} created={created_from_disk} "
                    f"linked={linked_from_disk}"
                )

            hashes = await HashStore.list(alias)
            if hashes:
                digest_metadata: list[tuple[str, Mapping[str, Any] | None]] = []
                for digest in hashes:
                    metadata = await HashStore.metadata(alias, digest)
                    meta_payload = metadata if isinstance(metadata, Mapping) else None
                    digest_metadata.append((digest, meta_payload))
                await HashStore.clear(alias)
                rehydrated, reingest_healed, last_dataset = await cls._reingest_from_hashstore(
                    alias, user, digest_metadata
                )
                reinserted += rehydrated
                healed_count += reingest_healed
            try:
                entries = await cls._list_dataset_entries(alias, user)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"knowledge_dataset_rebuild_list_retry_failed dataset={alias} detail={exc}")
                return RebuildResult()
            if not entries:
                storage_root = cls._storage_root()
                storage_info = CogneeConfig.describe_storage()
                dir_count = storage_info.get("entries_count", 0)
                root_size_bytes = storage_info.get("root_size_bytes", 0)
                cls._log_once(
                    logging.DEBUG,
                    "knowledge_rebuild_scan",
                    throttle_key=(alias, "rebuild_scan"),
                    dataset=alias,
                    dir_count=dir_count,
                    root_size_bytes=root_size_bytes,
                )
                files = sorted(p.name for p in storage_root.glob("text_*.txt") if cls._filename_to_digest(p.name))[:5]
                total_files = sum(1 for _ in storage_root.glob("text_*.txt"))
                logger.warning(
                    f"knowledge_dataset_rebuild_skipped dataset={alias}: no_entries "
                    f"storage_files={total_files} sample={files} dir_count={dir_count} root_size_bytes={root_size_bytes}"
                )
                return RebuildResult()
        for entry in entries:
            normalized = cls._normalize_text(entry.text)
            if not normalized:
                continue
            metadata = entry.metadata if isinstance(entry.metadata, Mapping) else None
            if metadata is None:
                metadata = cls._infer_metadata_from_text(normalized)
            meta_dict = dict(metadata) if metadata else None
            if meta_dict is not None:
                meta_dict.setdefault("dataset", alias)
            try:
                dataset_name, created = await cls.update_dataset(
                    normalized,
                    alias,
                    user,
                    node_set=None,
                    metadata=meta_dict,
                )
            except (DatasetNotFoundError, PermissionDeniedError):
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"knowledge_dataset_rebuild_add_failed dataset={alias} detail={exc}")
                continue
            last_dataset = dataset_name
            if created:
                reinserted += 1
        if reinserted == 0:
            logger.warning(f"knowledge_dataset_rebuild_skipped dataset={alias}: no_valid_entries")
            return RebuildResult()
        logger.info(f"knowledge_dataset_rebuild_ready dataset={alias} documents={reinserted} healed={healed_count}")
        result = RebuildResult(
            reinserted=reinserted, healed=healed_count, linked=linked_from_disk, rehydrated=rehydrated
        )
        if last_dataset:
            cls._LAST_REBUILD_RESULT[alias] = {
                "timestamp": time.time(),
                "documents": result.reinserted,
                "healed": result.healed,
                "sha_only": sha_only,
            }
        return result

    @classmethod
    async def _wait_for_projection(
        cls,
        dataset: str,
        user: Any | None,
        *,
        timeout_s: float | None = 5.0,
    ) -> ProjectionStatus:
        alias = cls._alias_for_dataset(dataset)
        state = cls._projection_state(alias)
        started = monotonic()
        fatal_error = False

        logger.debug(f"projection_wait start dataset={dataset}")
        try:
            await cls._ensure_dataset_exists(dataset, user)
        except Exception as exc:  # noqa: BLE001
            cls._log_once(logging.DEBUG, "projection:ensure_missing", dataset=alias, detail=exc)

        user_ctx = cls._to_user_ctx(user)
        if user_ctx is None:
            logger.debug(f"projection_wait done dataset={dataset} ok=False reason=user_context_unavailable")
            return ProjectionStatus.USER_CONTEXT_UNAVAILABLE

        ds_id = await cls._get_dataset_id(dataset, user)

        async def _ready() -> bool:
            nonlocal fatal_error
            try:
                return await cls._is_projection_ready(dataset, user_ctx=user_ctx, user=user)
            except ProjectionProbeError:
                fatal_error = True
                return False
            except Exception as probe_exc:  # noqa: BLE001
                cls._log_once(
                    logging.DEBUG,
                    "knowledge_projection_probe_error",
                    throttle_key=f"projection:{alias}:probe_exception",
                    dataset=alias,
                    detail=probe_exc,
                )
                return False

        if await _ready():
            cls._log_once(
                logging.DEBUG,
                "projection:ready",
                dataset=alias,
                elapsed_ms=int((monotonic() - started) * 1000),
                result="ready",
                id=ds_id,
                missing_files=state.get("missing_files", 0),
                healed_count=state.get("healed_count", 0),
                no_content_rows=state.get("no_content_rows", 0),
                min_interval=10.0,
            )
            logger.debug(f"projection_wait done dataset={dataset} ok=True reason=ready")
            return ProjectionStatus.READY
        if fatal_error:
            logger.debug(f"projection_wait done dataset={dataset} ok=False reason=fatal_error")
            return ProjectionStatus.FATAL_ERROR

        deadline = started + timeout_s if timeout_s and timeout_s > 0 else None
        backoff = cls._PROJECTION_BACKOFF_SECONDS or (0.5,)
        delay_index = 0
        delay = backoff[delay_index]
        while True:
            jitter = random.uniform(0.0, min(1.0, delay * 0.1))
            sleep_for = delay + jitter
            next_time = monotonic() + sleep_for
            if deadline is not None and next_time > deadline:
                break
            await asyncio.sleep(sleep_for)
            if await _ready():
                cls._log_once(
                    logging.DEBUG,
                    "projection:ready",
                    dataset=alias,
                    elapsed_ms=int((monotonic() - started) * 1000),
                    result="ready",
                    id=ds_id,
                    missing_files=state.get("missing_files", 0),
                    healed_count=state.get("healed_count", 0),
                    no_content_rows=state.get("no_content_rows", 0),
                    min_interval=10.0,
                )
                return ProjectionStatus.READY
            if fatal_error:
                return ProjectionStatus.FATAL_ERROR
            if delay_index < len(backoff) - 1:
                delay_index += 1
                delay = backoff[delay_index]

        elapsed_ms = int((monotonic() - started) * 1000)
        if timeout_s is not None and timeout_s > 0:
            cls._log_once(
                logging.INFO,
                "projection:timeout",
                dataset=alias,
                elapsed_ms=elapsed_ms,
                result="timeout",
                missing_files=state.get("missing_files", 0),
                healed_count=state.get("healed_count", 0),
                no_content_rows=state.get("no_content_rows", 0),
            )
            cls._log_once(
                logging.INFO,
                "projection:gate",
                dataset=alias,
                timeout_s=timeout_s,
                fallback="local_only",
            )
        ds_id = await cls._get_dataset_id(dataset, user)
        cls._log_once(
            logging.DEBUG,
            "projection:state",
            dataset=alias,
            status=state.get("status"),
            reason=state.get("reason"),
        )
        logger.debug(f"projection_wait done dataset={dataset} ok=False reason=timeout")
        return ProjectionStatus.TIMEOUT

    @classmethod
    def _log_storage_state(
        cls,
        dataset: str,
        *,
        missing_count: int | None = None,
        healed_count: int | None = None,
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

    @classmethod
    async def _is_projection_ready(
        cls,
        dataset: str,
        user_ctx: Any | None = None,  # Changed from user_id
        *,
        user: Any | None = None,
    ) -> bool:
        alias = KnowledgeBase._alias_for_dataset(dataset)
        state = cls._projection_state(alias)
        now = time.time()
        if now < state["next_check_ts"]:
            return state["status"] == "ready"

        datasets_module = getattr(cognee, "datasets", None)
        if datasets_module is None:
            cls._log_once(
                logging.DEBUG,
                "knowledge_projection_pending",
                throttle_key=(alias, "projection_pending", "datasets_module_missing"),
                dataset=alias,
                reason="datasets_module_missing",
                min_interval=15.0,
            )
            state["status"] = "pending"
            state["reason"] = "datasets_module_missing"
            state["next_check_ts"] = now + random.uniform(20.0, 40.0)
            logger.info(f"[projection_status] dataset={alias} projected_rows=0 is_pending=True timeout=N/A")
            return False
        list_data = getattr(datasets_module, "list_data", None)
        if not callable(list_data):
            cls._log_once(
                logging.DEBUG,
                "knowledge_projection_pending",
                throttle_key=(alias, "projection_pending", "list_data_missing"),
                dataset=alias,
                reason="list_data_missing",
                min_interval=15.0,
            )
            state["status"] = "pending"
            state["reason"] = "list_data_missing"
            state["next_check_ts"] = now + random.uniform(20.0, 40.0)
            logger.info(f"[projection_status] dataset={alias} projected_rows=0 is_pending=True timeout=N/A")
            return False

        list_data_callable = cast(Callable[..., Awaitable[Iterable[Any]]], list_data)
        try:
            rows = await cls._fetch_dataset_rows(list_data_callable, dataset, user)  # Changed user_ns to user_ctx
        except ProjectionProbeError as probe_exc:
            state["status"] = "pending"
            state["reason"] = "dataset_id_unavailable"
            state["next_check_ts"] = now + random.uniform(20.0, 40.0)
            cls._log_once(
                logging.WARNING,
                "knowledge_projection_pending",
                throttle_key=(alias, "projection_pending", "dataset_id_unavailable"),
                dataset=alias,
                reason="dataset_id_unavailable",
                detail=probe_exc,
                min_interval=30.0,
            )
            logger.info(f"[projection_status] dataset={alias} projected_rows=0 is_pending=True timeout=N/A")
            return False
        except Exception as exc:  # noqa: BLE001
            state["status"] = "pending"
            state["reason"] = "list_data_error"
            state["next_check_ts"] = now + random.uniform(45.0, 90.0)
            cls._log_once(
                logging.WARNING,
                "knowledge_projection_pending",
                throttle_key=(alias, "projection_pending", "list_data_error"),
                dataset=alias,
                reason="list_data_error",
                detail=f"{exc.__class__.__name__} {exc}",
                min_interval=30.0,
            )
            logger.info(f"[projection_status] dataset={alias} projected_rows=0 is_pending=True timeout=N/A")
            return False

        rows = list(rows)
        row_count = len(rows)
        cls._log_once(
            logging.DEBUG,
            "kb_projection_rows",
            throttle_key=f"projection:{alias}:row_count",
            dataset=alias,
            rows=row_count,
            min_interval=30.0,
        )
        doc_rows = 0
        message_rows = 0
        content_rows = 0
        missing_files = 0
        entries_snapshot: list[DatasetRow] = []
        no_content_rows = 0
        missing_files_sample: list[str] = []
        for raw_row in rows:
            try:
                prepared = cls._prepare_dataset_row(raw_row, alias)
            except Exception as exc:
                cls._log_once(
                    logging.WARNING,
                    "knowledge_projection_prepare_failed",
                    throttle_key=(alias, "prepare_dataset_row_failed"),
                    dataset=alias,
                    detail=exc,
                )
                continue

            entries_snapshot.append(prepared)
            metadata_map = prepared.metadata if isinstance(prepared.metadata, Mapping) else None
            digest_sha = cls._metadata_digest_sha(metadata_map)
            storage_path = cls._storage_path_for_sha(digest_sha) if digest_sha else None
            sha_exists = storage_path.exists() if storage_path else False
            storage_exists = sha_exists
            normalized_entry = cls._normalize_text(prepared.text)
            if not normalized_entry:
                if not storage_exists:
                    missing_files += 1
                    if len(missing_files_sample) < 5 and digest_sha:
                        missing_files_sample.append(digest_sha)
                else:
                    no_content_rows += 1
                continue
            content_rows += 1
            if not storage_exists:
                missing_files += 1
                if len(missing_files_sample) < 5 and digest_sha:
                    missing_files_sample.append(digest_sha)

            kind_value = cls._resolve_snippet_kind(prepared.metadata, normalized_entry)
            if kind_value == "message":
                message_rows += 1
            elif kind_value in {"document", "note"}:
                doc_rows += 1

        state["no_content_rows"] = no_content_rows
        state["missing_files"] = missing_files

        if row_count > 0 and content_rows == 0 and missing_files > 0:
            state["status"] = "pending"
            state["reason"] = "storage_missing"
            state["next_check_ts"] = now + random.uniform(5.0, 10.0)
            cls._log_once(
                logging.INFO,
                "knowledge_projection_pending",
                throttle_key=(alias, "projection_pending", "storage_missing"),
                dataset=alias,
                reason="storage_missing",
                rows=row_count,
                missing_files=missing_files,
                missing_files_sample=missing_files_sample,
                min_interval=15.0,
            )
            logger.info(f"[projection_status] dataset={alias} projected_rows={row_count} is_pending=True timeout=N/A")
            return False

        if doc_rows > 0:
            if await HashStore.list(alias):
                state["status"] = "ready"
                state["reason"] = None
                state["next_check_ts"] = now + random.uniform(300.0, 600.0)
                cls._log_once(
                    logging.DEBUG,
                    "knowledge_projection_ready",
                    throttle_key=(alias, "projection_ready"),
                    dataset=alias,
                    rows=row_count,
                    docs=doc_rows,
                    messages=message_rows,
                    missing_files=state.get("missing_files", 0),
                    healed_count=state.get("healed_count", 0),
                    no_content_rows=state.get("no_content_rows", 0),
                    min_interval=15.0,
                )
                logger.info(
                    f"[projection_status] dataset={alias} projected_rows={row_count} is_pending=False timeout=N/A"
                )
                return True

        if row_count > 0:
            state["status"] = "pending"
            state["reason"] = "no_documents"
            state["next_check_ts"] = now + random.uniform(10.0, 20.0)
            cls._log_once(
                logging.DEBUG,
                "knowledge_projection_pending",
                throttle_key=(alias, "projection_pending", "no_documents"),
                dataset=alias,
                reason="no_documents",
                rows=row_count,
                min_interval=15.0,
            )
            logger.info(f"[projection_status] dataset={alias} projected_rows={row_count} is_pending=True timeout=N/A")
            return False

        state["status"] = "pending"
        state["reason"] = "no_rows"
        state["next_check_ts"] = now + random.uniform(10.0, 20.0)
        cls._log_once(
            logging.DEBUG,
            "knowledge_projection_pending",
            throttle_key=(alias, "projection_pending", "no_rows"),
            dataset=alias,
            reason="no_rows",
            min_interval=15.0,
        )
        logger.info(f"[projection_status] dataset={alias} projected_rows=0 is_pending=True timeout=N/A")
        return False

    @classmethod
    async def _fallback_dataset_entries(
        cls,
        datasets: Sequence[str],
        user: Any | None,
        *,
        top_k: int | None,
    ) -> list[str]:
        """Return raw dataset entries when graph search is unavailable."""
        collected: list[str] = []
        limit = top_k or 6
        for dataset in datasets:
            rows = await cls._list_dataset_entries(dataset, user)
            if not rows:
                continue
            alias = cls._alias_for_dataset(dataset)
            for row in rows:
                normalized = cls._normalize_text(row.text)
                if not normalized:
                    continue
                metadata = row.metadata
                if metadata is None:
                    metadata = cls._infer_metadata_from_text(normalized)
                metadata_dict = dict(metadata) if metadata else {"kind": "document"}
                dig_sha = cls._compute_digests(normalized)
                ensured_metadata = cls._augment_metadata(metadata_dict, alias, digest_sha=dig_sha)
                cls._ensure_storage_file(
                    digest_sha=dig_sha,
                    text=normalized,
                    dataset=alias,
                )
                await HashStore.add(alias, dig_sha, metadata=ensured_metadata)
                if ensured_metadata.get("kind") == "message":
                    continue
                collected.append(normalized)
                if len(collected) >= limit:
                    return collected
        return collected

    @classmethod
    async def fallback_entries(cls, client_id: int, limit: int = 6) -> list[str]:
        """Expose raw dataset entries for resiliency fallbacks."""
        user = await cls._get_cognee_user()
        aliases = [cls._dataset_name(client_id), cls.GLOBAL_DATASET]
        datasets = [cls._resolve_dataset_alias(alias) for alias in aliases]
        return await cls._fallback_dataset_entries(datasets, user, top_k=limit)

    @classmethod
    async def _list_dataset_entries(cls, dataset: str, user: Any | None) -> list[DatasetRow]:
        alias = cls._alias_for_dataset(dataset)
        datasets_module = getattr(cognee, "datasets", None)
        if datasets_module is None:
            logger.debug(f"knowledge_dataset_list_skipped dataset={alias}: datasets module missing")
            return []
        list_data = getattr(datasets_module, "list_data", None)
        if not callable(list_data):
            logger.debug(f"knowledge_dataset_list_skipped dataset={alias}: list_data missing")
            return []
        try:
            await cls._ensure_dataset_exists(alias, user)
        except Exception as exc:  # pragma: no cover - best effort to keep flow running
            logger.debug(f"knowledge_dataset_ensure_failed dataset={alias} detail={exc}")
        user_ctx = cls._to_user_ctx(user)
        try:
            rows = await cls._fetch_dataset_rows(
                cast(Callable[..., Awaitable[Iterable[Any]]], list_data),
                alias,
                user,
            )
        except Exception as exc:  # noqa: BLE001 - dataset listing is best effort
            logger.debug(f"knowledge_dataset_list_failed dataset={alias} detail={exc}")
            return []
        rows_data: list[DatasetRow] = []
        for raw_row in rows:
            prepared = cls._prepare_dataset_row(raw_row, alias)
            normalized = cls._normalize_text(prepared.text)
            if not normalized:
                continue
            rows_data.append(DatasetRow(text=normalized, metadata=prepared.metadata))
        return rows_data

    @classmethod
    async def debug_snapshot(cls, client_id: int | None = None) -> dict[str, Any]:
        """Return diagnostic information about configured datasets."""
        user = await cls._get_cognee_user()
        aliases: list[str] = []
        if client_id is not None:
            aliases.append(cls._dataset_name(client_id))
        aliases.append(cls.GLOBAL_DATASET)
        seen: set[str] = set()
        datasets_info: list[dict[str, Any]] = []
        for alias in aliases:
            if alias in seen:
                continue
            seen.add(alias)
            info = await cls._build_dataset_snapshot(alias, user)
            datasets_info.append(info)
        return {"datasets": datasets_info}

    @classmethod
    async def _build_dataset_snapshot(cls, alias: str, user: Any | None) -> dict[str, Any]:
        resolved = cls._resolve_dataset_alias(alias)
        user_ctx = cls._to_user_ctx(user)
        info: dict[str, Any] = {
            "alias": alias,
            "resolved": resolved,
            "id": resolved,
            "documents": None,
            "projected": None,
            "last_error": None,
        }
        state = cls._projection_state(alias)
        info["no_content_rows"] = state.get("no_content_rows", 0)
        info["missing_files"] = state.get("missing_files", 0)
        info["healed_count"] = state.get("healed_count", 0)
        metadata = await cls._get_dataset_metadata(resolved, user)
        if metadata is not None:
            identifier = getattr(metadata, "id", None) or getattr(metadata, "dataset_id", None)
            if identifier:
                info["id"] = str(identifier)
            updated_at = getattr(metadata, "updated_at", None) or getattr(metadata, "updatedAt", None)
            if updated_at is not None:
                info["updated_at"] = str(updated_at)
        try:
            entries = await cls._list_dataset_entries(resolved, user)
        except Exception as exc:  # noqa: BLE001
            info["last_error"] = str(exc)
            entries = []
        if entries:
            info["documents"] = sum(
                1
                for row in entries
                if row.text.strip() and cls._resolve_snippet_kind(row.metadata, row.text) != "message"
            )
        else:
            info["documents"] = 0
        user_ctx = cls._to_user_ctx(user)
        try:
            info["projected"] = await cls._is_projection_ready(resolved, user_ctx=user_ctx, user=user)
        except Exception as exc:
            info["last_error"] = str(exc)
        return info

    @classmethod
    async def _resolve_dataset_identifier(cls, dataset: str, user: Any | None) -> str:
        alias = cls._alias_for_dataset(dataset)
        mapped = cls._DATASET_IDS.get(alias)
        if mapped:
            return mapped
        metadata = await cls._get_dataset_metadata(alias, user)
        if metadata is not None:
            identifier = cls._extract_dataset_identifier(metadata)
            if identifier:
                cls._register_dataset_identifier(alias, identifier)
                return identifier
        return alias

    @classmethod
    async def _get_dataset_metadata(cls, dataset: str, user: Any | None) -> Any | None:
        try:  # pragma: no cover - optional dependency
            from cognee.modules.data.methods import get_authorized_dataset_by_name  # type: ignore
        except Exception:
            return None
        user_ctx = cls._to_user_ctx(user)
        try:
            return await get_authorized_dataset_by_name(dataset, user_ctx, "read")
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"knowledge_dataset_metadata_failed dataset={dataset} detail={exc}")
            return None
