import asyncio
import time
import logging
from hashlib import sha256
from time import monotonic
from pathlib import Path
from typing import Any, ClassVar, Mapping, Optional, Sequence, TYPE_CHECKING

import cognee
from loguru import logger

from ai_coach.agent.knowledge.base_knowledge_loader import KnowledgeLoader
from ai_coach.agent.knowledge.schemas import KnowledgeSnippet, ProjectionStatus, RebuildResult
from ai_coach.agent.knowledge.utils.chat_queue import ChatProjectionScheduler
from ai_coach.agent.knowledge.cognee_config import CogneeConfig
from ai_coach.agent.knowledge.utils.datasets import DatasetService
from ai_coach.agent.knowledge.utils.hash_store import HashStore
from ai_coach.agent.knowledge.utils.projection import ProjectionService
from ai_coach.agent.knowledge.utils.search import SearchService
from ai_coach.agent.knowledge.utils.storage import StorageService
from ai_coach.agent.knowledge.utils.lock_cache import LockCache
from ai_coach.types import MessageRole
from config.app_settings import settings
from core.services import APIService as _APIService

if TYPE_CHECKING:
    from core.schemas import Client

APIService = _APIService


async def _safe_add(
    text: str,
    *,
    dataset_name: str,
    user: Any,
    node_set: list[str] | None,
) -> Any:
    import cognee

    return await cognee.add(text, dataset_name=dataset_name, user=user, node_set=list(node_set or []))


class KnowledgeBase:
    """Cognee-backed knowledge storage for the coach agent."""

    _loader: KnowledgeLoader | None = None
    _cognify_locks: LockCache = LockCache()
    _user: Any | None = None
    _warned_missing_user: bool = False
    _PENDING_REBUILDS: ClassVar[set[str]] = set()
    _LAST_REBUILD_RESULT: ClassVar[dict[str, Any]] = {}
    _legacy_singleton: ClassVar[Optional["KnowledgeBase"]] = None
    _PROJECTED_DATASETS: ClassVar[set[str]] = DatasetService._PROJECTED_DATASETS
    _DATASET_IDS: ClassVar[dict[str, str]] = DatasetService._DATASET_IDS
    GLOBAL_DATASET: str = settings.COGNEE_GLOBAL_DATASET

    def __init__(self) -> None:
        self._projection_health: dict[str, tuple[ProjectionStatus, str]] = {}
        self.dataset_service = DatasetService()
        self.storage_service = StorageService(self.dataset_service)
        self.projection_service = ProjectionService(self.dataset_service, self.storage_service)
        self.storage_service.attach_knowledge_base(self)
        self.projection_service.attach_knowledge_base(self)
        self.projection_service.set_waiter(self._wait_for_projection)
        self.search_service = SearchService(self.dataset_service, self.projection_service, knowledge_base=self)
        self.chat_queue_service = ChatProjectionScheduler(self.dataset_service, self)

    async def initialize(self, knowledge_loader: KnowledgeLoader | None = None) -> None:
        CogneeConfig.apply()
        try:
            from cognee.modules.engine.operations.setup import setup as cognee_setup

            await cognee_setup()
        except Exception:
            pass
        self._loader = knowledge_loader
        self._user = await self.dataset_service.get_cognee_user()
        if not getattr(self._user, "id", None):
            logger.warning("KB user is missing id, skipping heavy initialization steps.")
            return

        self.dataset_service._PROJECTED_DATASETS.clear()
        try:
            await self.storage_service.sanitize_hash_store()
        except Exception as exc:
            logger.warning(f"kb_hashstore_sanitation_failed detail={exc}")

        try:
            await self.rebuild_dataset(self.GLOBAL_DATASET, self._user, sha_only=True)
        except Exception as exc:
            logger.warning(f"kb_global_rebuild_failed detail={exc}")
        try:
            await self.refresh()
        except Exception as e:
            logger.warning(f"Knowledge refresh skipped: {e}")

    async def refresh(self) -> None:
        import cognee
        from cognee.modules.data.exceptions import DatasetNotFoundError
        from cognee.modules.users.exceptions.exceptions import PermissionDeniedError

        user = await self.dataset_service.get_cognee_user()
        ds = self.dataset_service.alias_for_dataset(self.GLOBAL_DATASET)
        user_ctx = self.dataset_service.to_user_ctx(user)
        if user_ctx is None:
            logger.warning(f"knowledge_refresh_skipped dataset={ds}: user context unavailable")
            return
        await self.dataset_service.ensure_dataset_exists(ds, user_ctx)
        self.dataset_service._PROJECTED_DATASETS.discard(ds)
        if self._loader:
            await self._loader.refresh()
        target = ds
        try:
            dataset_id = await self.dataset_service.get_dataset_id(ds, user_ctx)
        except Exception:
            dataset_id = None
        if dataset_id:
            target = dataset_id
        try:
            await cognee.cognify(datasets=[target], user=user_ctx)
        except (PermissionDeniedError, DatasetNotFoundError) as e:
            logger.error(f"Knowledge base update skipped: {e}")

    async def search(
        self, query: str, client_id: int, k: int | None = None, *, request_id: str | None = None
    ) -> list[KnowledgeSnippet]:
        normalized_query = self.dataset_service._normalize_text(query)
        q_hash = sha256(normalized_query.encode("utf-8")).hexdigest()[:12] if normalized_query else "empty"
        user = await self.dataset_service.get_cognee_user()
        datasets_order = [
            self.dataset_service.chat_dataset_name(client_id),
            self.GLOBAL_DATASET,
        ]
        searchable_aliases: list[str] = []
        seen: set[str] = set()
        effective_list: list[str] = []
        raw_list: list[str] = []
        counts_map: dict[str, dict[str, int]] = {}
        for dataset in datasets_order:
            raw = dataset
            # Resolve canonical alias and any registered identifier
            alias = self.dataset_service.resolve_dataset_alias(raw)
            identifier = self.dataset_service.get_registered_identifier(alias)
            # Probe row counts for alias and identifier separately
            row_count_ident: int | None = None
            row_count_alias = await self.dataset_service.get_row_count(alias, user=user)
            if identifier and identifier != alias:
                row_count_ident = await self.dataset_service.get_row_count(identifier, user=user)
            logger.debug(
                f"ask.search.alias_resolve raw={raw} alias={alias} ident={identifier} "
                f"rows_alias={row_count_alias} rows_ident={row_count_ident}"
            )
            if row_count_alias == 0 and (row_count_ident or 0) > 0:
                logger.warning(
                    f"ask.search.mismatch raw={raw} alias={alias} ident={identifier} reason=rows_under_identifier_only"
                )
            # Choose effective target for search: prefer alias if non-empty, otherwise identifier rows
            row_count = row_count_alias if row_count_alias is not None else 0
            effective = alias
            if row_count == 0 and (row_count_ident or 0) > 0 and identifier:
                row_count = int(row_count_ident or 0)
                effective = identifier
            if effective in seen:
                continue
            seen.add(effective)
            if row_count > 0:
                # Ensure projection is ready before searching
                await self.projection_service.ensure_dataset_projected(effective, user, timeout_s=2.0)
                counts_map[effective] = await self.dataset_service.get_counts(effective, user)
                counts_payload = counts_map[effective]
                if (counts_payload.get("text_rows", 0) or 0) > 0 and (
                    (counts_payload.get("chunk_rows", 0) or 0) == 0 and (counts_payload.get("graph_nodes", 0) or 0) == 0
                ):
                    # This means text rows exist, but chunks/graph nodes are missing after projection
                    # This can happen if the projection failed or is still pending
                    self.dataset_service.log_once(
                        logging.ERROR,
                        "projection:empty_after_text",
                        dataset=effective,
                        text_rows=counts_payload.get("text_rows"),
                        chunk_rows=counts_payload.get("chunk_rows"),
                        graph_nodes=counts_payload.get("graph_nodes"),
                        min_interval=60.0,
                    )
                    logger.warning(
                        f"projection:empty_after_text dataset={effective} reason=no_chunks_or_graph_nodes_after_text_rows"
                    )
                    # Do not add to searchable_aliases if projection is incomplete
                    continue

                searchable_aliases.append(effective)
                effective_list.append(effective)
                raw_list.append(raw)
                # The original logic for counts_map update is now handled by the diagnostic check above
                continue
            self.dataset_service.log_once(
                logging.INFO,
                "projection:skip_no_rows",
                dataset=effective,
                stage="search",
                min_interval=120.0,
            )
            logger.debug(f"projection:skip_no_rows dataset={effective} stage=search")
        if effective_list:
            rows_payload = {k: v for k, v in counts_map.items()}
            logger.debug(f"search.inputs raw={raw_list} effective={effective_list} rows={rows_payload}")
        dataset_label = ",".join(searchable_aliases) if searchable_aliases else "none"
        logger.debug(f"ask.search.start client_id={client_id} datasets={dataset_label} q_hash={q_hash}")
        if not searchable_aliases:
            logger.debug(f"kb.search dataset={dataset_label} q_hash={q_hash} hits=0")
            logger.debug(f"ask.search.done client_id={client_id} datasets={dataset_label} entries=0")
            return []
        try:
            results = await self.search_service.search(
                query,
                client_id,
                k,
                request_id=request_id,
                datasets=searchable_aliases,
                user=user,
            )
        except Exception as exc:
            logger.debug(f"kb.search.fail detail={exc}")
            raise
        hits = len(results)
        logger.debug(f"kb.search dataset={dataset_label} q_hash={q_hash} hits={hits}")
        logger.debug(f"ask.search.done client_id={client_id} datasets={dataset_label} entries={hits}")
        return results

    async def add_text(
        self,
        text: str,
        *,
        dataset: str | None = None,
        node_set: list[str] | None = None,
        client_id: int | None = None,
        role: MessageRole | None = None,
        metadata: dict[str, Any] | None = None,
        project: bool = True,
    ) -> None:
        user = await self.dataset_service.get_cognee_user()
        ds = dataset or (self.dataset_service.dataset_name(client_id) if client_id is not None else self.GLOBAL_DATASET)
        target_alias = self.dataset_service.alias_for_dataset(ds)
        meta_payload: dict[str, Any] = {}
        if metadata:
            meta_payload.update(dict(metadata))

        if role:
            text = f"{role.value}: {text}"
            meta_payload.setdefault("kind", "message")
            meta_payload.setdefault("role", role.value)
        else:
            meta_payload.setdefault("kind", "document")

        payload_bytes = len(text.encode("utf-8"))
        normalized_text = self.dataset_service._normalize_text(text)
        logger.debug(f"kb.add_text dataset={target_alias} bytes={payload_bytes}")
        if not normalized_text.strip():
            self.dataset_service.log_once(
                logging.INFO,
                "empty_content_filtered",
                dataset=ds,
                role=role.value if role else "document",
                min_interval=30.0,
            )
            return

        meta_payload.setdefault("dataset", target_alias)

        attempts = 0
        backoffs = (0.5,)
        while attempts < 2:
            try:
                resolved_name, created = await self.update_dataset(
                    normalized_text,
                    target_alias,
                    user,
                    node_set=list(node_set or []),
                    metadata=meta_payload,
                )
                if created:
                    alias = target_alias
                    if not project or self.dataset_service.is_chat_dataset(alias):
                        pending = self.chat_queue_service.queue_chat_dataset(alias)
                        logger.debug(f"kb_chat_ingest queued={pending} dataset={alias}")
                        self.chat_queue_service.ensure_chat_projection_task(alias)
                    else:
                        task = asyncio.create_task(self._process_dataset(resolved_name, user))
                        task.add_done_callback(self._log_task_exception)
                return
            except Exception as exc:
                attempts += 1
                if attempts >= 2:
                    logger.warning(f"kb_append aborted dataset={target_alias}: {exc}", exc_info=True)
                    break
                sleep_for = backoffs[min(attempts - 1, len(backoffs) - 1)]
                logger.debug(f"kb_append.retry dataset={target_alias} attempt={attempts} sleep_for={sleep_for}")
                await asyncio.sleep(sleep_for)

    async def save_client_message(self, text: str, client_id: int) -> None:
        await self.add_text(
            text,
            dataset=self.dataset_service.chat_dataset_name(client_id),
            client_id=client_id,
            role=MessageRole.CLIENT,
            node_set=[f"client:{client_id}", "chat_message"],
            metadata={"channel": "chat"},
            project=False,
        )

    async def save_ai_message(self, text: str, client_id: int) -> None:
        await self.add_text(
            text,
            dataset=self.dataset_service.chat_dataset_name(client_id),
            client_id=client_id,
            role=MessageRole.AI_COACH,
            node_set=[f"client:{client_id}", "chat_message"],
            metadata={"channel": "chat"},
            project=False,
        )

    async def get_message_history(self, client_id: int, limit: int | None = None) -> list[str]:
        dataset: str = self.dataset_service.alias_for_dataset(self.dataset_service.chat_dataset_name(client_id))
        user: Any | None = await self.dataset_service.get_cognee_user()
        if user is None:
            if not self._warned_missing_user:
                logger.warning(f"History fetch skipped client_id={client_id}: default user unavailable")
                self._warned_missing_user = True
            else:
                logger.debug(f"History fetch skipped client_id={client_id}: default user unavailable")
            return []
        user_ctx: Any | None = self.dataset_service.to_user_ctx(user)
        try:
            await self.dataset_service.ensure_dataset_exists(dataset, user_ctx)
        except Exception as exc:
            logger.debug(f"Dataset ensure skipped client_id={client_id}: {exc}")
        try:
            data = await self.dataset_service.list_dataset_entries(dataset, user_ctx)
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

    async def update_dataset(
        self,
        text: str,
        dataset: str,
        user: Any | None = None,
        node_set: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, bool]:
        from ai_coach.agent.knowledge.utils.hash_store import HashStore

        normalized_text = self.dataset_service._normalize_text(text)
        if not normalized_text.strip():
            self.dataset_service.log_once(
                logging.INFO,
                "empty_content_filtered",
                dataset=dataset,
                min_interval=30.0,
            )
            return dataset, False
        alias = self.dataset_service.alias_for_dataset(dataset)
        actor = user if user is not None else self._user
        if actor is None:
            self.dataset_service.log_once(
                logging.WARNING,
                "knowledge_update_dataset_failed",
                dataset=alias,
                reason="missing_user",
                min_interval=30.0,
            )
            logger.warning(f"knowledge_update_dataset_failed dataset={alias} reason=missing_user")
            raise RuntimeError("update_dataset_failed_missing_user")
        ds_name = alias
        digest_sha = self.storage_service.compute_digests(normalized_text, dataset_alias=ds_name)
        user_ctx = self.dataset_service.to_user_ctx(actor)
        if user_ctx is None:
            logger.warning(f"knowledge_update_dataset_failed dataset={ds_name} reason=user_context_unavailable")
            raise RuntimeError("update_dataset_failed_user_context")
        await self.dataset_service.ensure_dataset_exists(ds_name, user_ctx)
        rows_before = await self.dataset_service.get_row_count(alias, user=actor)
        inferred_metadata = self.dataset_service._infer_metadata_from_text(normalized_text, metadata)
        metadata_payload = self.storage_service.augment_metadata(inferred_metadata, ds_name, digest_sha=digest_sha)
        storage_path, created_file = self.storage_service.ensure_storage_file(
            digest_sha=digest_sha, text=normalized_text, dataset=ds_name
        )
        if storage_path is None:
            logger.debug(f"kb.update dataset={alias} rows_before={rows_before} rows_after={rows_before}")
            return ds_name, False
        if await HashStore.contains(ds_name, digest_sha):
            await HashStore.add(ds_name, digest_sha, metadata=metadata_payload)
            logger.debug(f"kb_append skipped dataset={ds_name} digest_sha={digest_sha[:12]} reason=duplicate")
            logger.debug(f"kb.update dataset={alias} rows_before={rows_before} rows_after={rows_before}")
            return ds_name, False

        info: Any | None = None
        try:
            info = await _safe_add(normalized_text, dataset_name=ds_name, user=user_ctx, node_set=list(node_set or []))
        except Exception as exc:
            raise RuntimeError(f"Failed to add dataset entry for {ds_name}") from exc

        await HashStore.add(ds_name, digest_sha, metadata=metadata_payload)
        resolved = ds_name
        identifier = self.dataset_service._extract_dataset_identifier(info)
        if identifier:
            self.dataset_service.register_dataset_identifier(ds_name, identifier)
            resolved = identifier
        resolved_alias = self.dataset_service.alias_for_dataset(resolved)
        rows_after = await self.dataset_service.get_row_count(resolved_alias, user=actor)
        logger.debug(
            "kb.update rows raw=%s alias=%s resolved=%s rows_before=%s rows_after=%s digest=%s",
            dataset,
            ds_name,
            resolved_alias,
            rows_before,
            rows_after,
            digest_sha[:12],
        )
        # Trigger projection and wait briefly to avoid projection:skip_no_rows
        try:
            self.dataset_service.log_once(logging.INFO, "projection:requested", dataset=resolved_alias, reason="ingest")
            await self.projection_service.project_dataset(resolved_alias, actor, allow_rebuild=False)
            await self._wait_for_projection(resolved_alias, actor, timeout_s=15.0)
            # Diagnostics per layer
            counts = await self.dataset_service.get_counts(resolved_alias, actor)
            logger.info(
                (
                    f"projection:ready dataset={resolved_alias} text_rows={counts.get('text_rows')} "
                    f"chunk_rows={counts.get('chunk_rows')} graph_nodes={counts.get('graph_nodes')} "
                    f"graph_edges={counts.get('graph_edges')}"
                )
            )
            if (counts.get("text_rows", 0) or 0) > 0 and (counts.get("chunk_rows", 0) or 0) == 0:
                preview = (normalized_text or "")[:400]
                logger.error(
                    f"projection:empty_after_text dataset={resolved_alias} digest={digest_sha[:12]} preview={preview}"
                )
        except Exception as exc:
            logger.debug(f"projection:post_ingest_diag_skipped dataset={resolved_alias} detail={exc}")
        return resolved, True

    async def _process_dataset(self, dataset: str, user: Any | None = None) -> None:
        lock = self._cognify_locks.get(dataset)
        async with lock:
            alias = self.dataset_service.alias_for_dataset(dataset)
            actor = user if user is not None else self._user
            if actor is None:
                logger.debug(f"projection:process_skipped dataset={alias} reason=missing_user")
                return
            user_ctx = self.dataset_service.to_user_ctx(actor)
            try:
                dataset_id = await self.dataset_service.get_dataset_id(alias, user_ctx)
            except Exception:
                dataset_id = None
            self.dataset_service.log_once(
                logging.DEBUG,
                "projection:process",
                dataset=alias,
                dataset_id=dataset_id,
                min_interval=5.0,
            )
            await self.projection_service.project_dataset(alias, actor, allow_rebuild=True)
            await self.projection_service.wait(
                alias,
                actor,
                timeout=settings.AI_COACH_GLOBAL_PROJECTION_TIMEOUT,
            )

    @staticmethod
    def _log_task_exception(task: asyncio.Task[Any]) -> None:
        if exc := task.exception():
            logger.warning(f"Dataset processing failed: {exc}", exc_info=True)

    async def _wait_for_projection(
        self,
        dataset: str,
        user: Any | None = None,
        *,
        timeout_s: float | None = None,
        **kwargs: Any,
    ) -> ProjectionStatus:
        timeout_legacy = kwargs.pop("timeout", None)
        if timeout_s is None and timeout_legacy is not None:
            try:
                timeout_s = float(timeout_legacy)
            except (TypeError, ValueError):
                timeout_s = None
        extra_keys = tuple(kwargs.keys())
        alias = self.dataset_service.alias_for_dataset(dataset)
        if extra_keys:
            logger.debug(f"projection:wait_extra_args dataset={alias} keys={list(extra_keys)}")

        actor = user if user is not None else self._user
        if actor is None:
            self.dataset_service.log_once(
                logging.WARNING,
                "projection:wait_skipped",
                dataset=alias,
                reason="missing_user",
                min_interval=30.0,
            )
            status = ProjectionStatus.USER_CONTEXT_UNAVAILABLE
            self._projection_health[alias] = (status, "missing_user")
            self.projection_service.record_wait_attempts(alias, 0, status)
            return status

        user_ctx = self.dataset_service.to_user_ctx(actor)
        if user_ctx is None:
            self.dataset_service.log_once(
                logging.WARNING,
                "projection:wait_skipped",
                dataset=alias,
                reason="user_context_unavailable",
                min_interval=30.0,
            )
            status = ProjectionStatus.USER_CONTEXT_UNAVAILABLE
            self._projection_health[alias] = (status, "user_context_unavailable")
            self.projection_service.record_wait_attempts(alias, 0, status)
            return status

        effective_timeout = timeout_s if timeout_s is not None else 45.0
        deadline = monotonic() + max(effective_timeout, 0.0)
        backoff = (0.5, 1.0, 2.0, 5.0, 8.0)
        attempts = 0

        while True:
            attempts += 1
            ready, reason = await self.projection_service.probe(alias, actor)
            if not ready:
                provisional = ProjectionStatus.FATAL_ERROR if reason == "fatal_error" else ProjectionStatus.TIMEOUT
                self._projection_health[alias] = (provisional, reason)
            if ready:
                self.dataset_service.log_once(
                    logging.DEBUG,
                    "projection:wait_ready",
                    dataset=alias,
                    reason=reason,
                    min_interval=5.0,
                )
                status = ProjectionStatus.READY
                self.dataset_service.add_projected_dataset(alias)
                self._projection_health[alias] = (status, reason)
                self.projection_service.record_wait_attempts(alias, attempts, status)
                return status

            if reason == "no_rows_in_dataset":
                status = ProjectionStatus.READY_EMPTY
                self.dataset_service.add_projected_dataset(alias)
                self._projection_health[alias] = (status, reason)
                self.projection_service.record_wait_attempts(alias, attempts, status)
                return status

            if reason == "fatal_error":
                self.dataset_service.log_once(
                    logging.WARNING,
                    "projection:fatal_error",
                    dataset=alias,
                    min_interval=30.0,
                )
                status = ProjectionStatus.FATAL_ERROR
                self._projection_health[alias] = (status, reason)
                self.projection_service.record_wait_attempts(alias, attempts, status)
                return status

            if reason == "not_found":
                self.dataset_service.log_once(
                    logging.WARNING,
                    "projection:not_found",
                    dataset=alias,
                    min_interval=30.0,
                )
                status = ProjectionStatus.TIMEOUT
                self._projection_health[alias] = (status, reason)
                self.projection_service.record_wait_attempts(alias, attempts, status)
                return status

            now = monotonic()
            if now >= deadline:
                self.dataset_service.log_once(
                    logging.WARNING,
                    "projection:wait_timeout",
                    dataset=alias,
                    reason=reason,
                    timeout_s=effective_timeout,
                )
                status = ProjectionStatus.TIMEOUT
                self._projection_health[alias] = (status, reason)
                self.projection_service.record_wait_attempts(alias, attempts, status)
                return status

            sleep_for = backoff[min(attempts - 1, len(backoff) - 1)]
            self.dataset_service.log_once(
                logging.DEBUG,
                "projection:wait_pending",
                dataset=alias,
                attempts=attempts,
                reason=reason,
                sleep_for=sleep_for,
                min_interval=5.0,
            )
            await asyncio.sleep(sleep_for)

    async def rebuild_dataset(self, dataset: str, user: Any | None, sha_only: bool = False) -> "RebuildResult":
        alias = self.dataset_service.alias_for_dataset(dataset)
        user_ctx = self.dataset_service.to_user_ctx(user)
        reinserted = 0
        healed_count = 0
        linked_from_disk = 0
        rehydrated = 0

        try:
            await self.dataset_service.ensure_dataset_exists(alias, user_ctx)
        except Exception as exc:
            logger.warning(f"knowledge_dataset_rebuild_ensure_failed dataset={alias} detail={exc}")
        await self.storage_service.heal_dataset_storage(alias, user_ctx, reason="rebuild_preflight")
        from ai_coach.agent.knowledge.utils.hash_store import HashStore

        await HashStore.clear(alias)
        self.dataset_service._PROJECTED_DATASETS.discard(alias)
        try:
            entries = await self.dataset_service.list_dataset_entries(alias, user_ctx)
        except Exception as exc:
            logger.warning(f"knowledge_dataset_rebuild_list_failed dataset={alias} detail={exc}")
            return RebuildResult()
        last_dataset: str | None = None
        if not entries:
            created_from_disk, linked_from_disk = await self.storage_service.rebuild_from_disk(alias)
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
                reingest_result = await self.storage_service.reingest_from_hashstore(
                    alias,
                    user,
                    digest_metadata,
                    knowledge_base=self,
                )
                rehydrated += int(reingest_result.rehydrated)
                reinserted += int(reingest_result.rehydrated)
                healed_count += reingest_result.healed_documents
                if reingest_result.last_dataset:
                    last_dataset = reingest_result.last_dataset
                if not reingest_result.healed:
                    reingest_result.reinserted = reinserted
                    reingest_result.healed_documents = healed_count
                    reingest_result.linked = linked_from_disk
                    reingest_result.rehydrated = rehydrated
                    return reingest_result
            try:
                entries = await self.dataset_service.list_dataset_entries(alias, user_ctx)
            except Exception as exc:
                logger.warning(f"knowledge_dataset_rebuild_list_retry_failed dataset={alias} detail={exc}")
                return RebuildResult()
            if not entries:
                return RebuildResult()
        for entry in entries:
            normalized = self.dataset_service._normalize_text(entry.text)
            if not normalized:
                continue
            entry_metadata = dict(entry.metadata) if isinstance(entry.metadata, Mapping) else {}
            entry_metadata.setdefault("dataset", alias)
            meta_dict = self.dataset_service._infer_metadata_from_text(normalized, entry_metadata)
            try:
                dataset_name, created = await self.update_dataset(
                    normalized,
                    alias,
                    user,
                    node_set=None,
                    metadata=meta_dict,
                )
            except Exception as exc:
                logger.warning(f"knowledge_dataset_rebuild_add_failed dataset={alias} detail={exc}")
                continue
            last_dataset = dataset_name
            if created:
                reinserted += 1
        if reinserted == 0:
            logger.warning(f"knowledge_dataset_rebuild_skipped dataset={alias}: no_valid_entries")
            return RebuildResult(
                reinserted=0,
                healed_documents=healed_count,
                linked=linked_from_disk,
                rehydrated=rehydrated,
                last_dataset=last_dataset,
                healed=True,
                reason="no_valid_entries",
            )
        logger.info(f"knowledge_dataset_rebuild_ready dataset={alias} documents={reinserted} healed={healed_count}")
        result = RebuildResult(
            reinserted=reinserted,
            healed_documents=healed_count,
            linked=linked_from_disk,
            rehydrated=rehydrated,
            last_dataset=last_dataset,
            healed=True,
            reason="ok",
        )
        if last_dataset:
            self._LAST_REBUILD_RESULT[alias] = {
                "timestamp": time.time(),
                "documents": result.reinserted,
                "healed": result.healed_documents,
                "sha_only": sha_only,
            }
        return result

    async def fallback_entries(self, client_id: int, limit: int = 6) -> list[tuple[str, str]]:
        return await self.search_service.fallback_entries(client_id, limit)

    def chat_dataset_name(self, client_id: int) -> str:
        return self.dataset_service.chat_dataset_name(client_id)

    def get_last_rebuild_result(self) -> dict[str, Any]:
        return self._LAST_REBUILD_RESULT

    def get_projection_health(self, dataset: str) -> tuple[ProjectionStatus, str] | None:
        alias = self.dataset_service.alias_for_dataset(dataset)
        return self._projection_health.get(alias)

    async def prune(self) -> None:
        from ai_coach.agent.knowledge.utils.hash_store import HashStore
        from cognee.modules.data.deletion import prune_data as cognee_prune_data
        from cognee.modules.data.deletion import prune_system as cognee_prune_system

        logger.info("cognee_prune.started")
        steps_completed: list[str] = []
        failures: list[str] = []

        try:
            await cognee_prune_data()
            steps_completed.append("data_storage")
            logger.info("cognee_prune.data_storage_cleared")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"data:{exc}")
            logger.warning(f"cognee_prune.data_failed detail={exc}")

        try:
            await cognee_prune_system(graph=True, vector=True, metadata=False, cache=True)
            steps_completed.append("system_cache")
            logger.info("cognee_prune.system_cache_cleared graph=True vector=True cache=True metadata=False")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"system:{exc}")
            logger.warning(f"cognee_prune.system_failed detail={exc}")

        try:
            datasets = await HashStore.list_all_datasets()
            if datasets:
                await asyncio.gather(*(HashStore.clear(dataset) for dataset in datasets))
            steps_completed.append("hash_store")
            logger.info(f"cognee_prune.hash_store_cleared datasets={len(datasets)}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"hash_store:{exc}")
            logger.warning(f"cognee_prune.hash_store_failed detail={exc}")

        type(self.dataset_service)._PROJECTED_DATASETS.clear()
        type(self.dataset_service)._DATASET_IDS.clear()
        type(self.dataset_service)._DATASET_ALIASES.clear()
        self._projection_health.clear()
        self.storage_service._STORAGE_CACHE.clear()

        if failures:
            raise RuntimeError(f"cognee_prune_incomplete steps={steps_completed} errors={failures}")

        logger.info("cognee_prune.completed steps={}".format(",".join(steps_completed)))

    @staticmethod
    def _is_graph_missing_error(exc: Exception) -> bool:
        message = str(exc)
        if "Empty graph" in message or "empty graph" in message:
            return True
        if "EntityNotFound" in exc.__class__.__name__:
            return True
        status = getattr(exc, "status_code", None)
        return status == 404

    @staticmethod
    def _client_profile_text(client: "Client") -> str:
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
    def _legacy_instance(cls) -> "KnowledgeBase":
        if cls._legacy_singleton is None:
            cls._legacy_singleton = cls()
        return cls._legacy_singleton

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        return DatasetService._normalize_text(value)

    @classmethod
    def _dataset_name(cls, client_id: int) -> str:
        return cls._legacy_instance().dataset_service.dataset_name(client_id)

    @classmethod
    def _resolve_dataset_alias(cls, name: str) -> str:
        return cls._legacy_instance().dataset_service._resolve_dataset_alias(str(name))

    @classmethod
    def _storage_root(cls) -> Path:
        return cls._legacy_instance().storage_service.storage_root()

    @classmethod
    def _ensure_storage_file(cls, digest_md5: str, text: str, *, dataset: str | None = None) -> tuple[Path | None, bool]:
        instance = cls._legacy_instance()
        normalized = instance.dataset_service._normalize_text(text)
        digest_sha = sha256(normalized.encode("utf-8")).hexdigest()
        return instance.storage_service.ensure_storage_file(
            digest_sha=digest_sha,
            text=normalized,
            dataset=dataset,
        )

    @classmethod
    async def _ensure_dataset_exists(cls, name: str, user: Any | None) -> None:
        instance = cls._legacy_instance()
        user_ctx = instance.dataset_service.to_user_ctx(user)
        if user_ctx is None:
            base_user = user or await instance.dataset_service.get_cognee_user()
            user_ctx = instance.dataset_service.to_user_ctx(base_user)
        await instance.dataset_service.ensure_dataset_exists(name, user_ctx)

    @classmethod
    async def _list_dataset_entries(cls, dataset: str, user: Any | None) -> list[Any]:
        instance = cls._legacy_instance()
        user_ctx = instance.dataset_service.to_user_ctx(user)
        if user_ctx is None:
            base_user = user or await instance.dataset_service.get_cognee_user()
            user_ctx = instance.dataset_service.to_user_ctx(base_user)
        return await instance.dataset_service.list_dataset_entries(dataset, user_ctx)

    @classmethod
    async def _collect_metadata(
        cls, digest: str, datasets: Sequence[str]
    ) -> tuple[str | None, Mapping[str, Any] | None]:
        instance = cls._legacy_instance()
        return await instance.search_service._collect_metadata(digest, list(datasets))

    @classmethod
    async def _ensure_profile_indexed(cls, client_id: int, user: Any | None) -> None:
        try:
            client = await APIService.profile.get_client(client_id)
        except Exception:
            return
        if not client:
            return
        instance = cls._legacy_instance()
        actor = user
        if actor is None:
            actor = await instance.dataset_service.get_cognee_user()
        if actor is None:
            return
        text = instance._client_profile_text(client)
        dataset = instance.dataset_service.dataset_name(client_id)
        dataset, created = await instance.update_dataset(
            text,
            dataset,
            actor,
            node_set=["client_profile"],
            metadata={"kind": "document", "source": "client_profile"},
        )
        if created:
            await instance._process_dataset(dataset, actor)

    @classmethod
    async def _get_cognee_user(cls) -> Any | None:
        return await cls._legacy_instance().dataset_service.get_cognee_user()

    @classmethod
    async def _process_dataset(cls, dataset: str, user: Any | None = None) -> None:
        await cls._legacy_instance()._process_dataset(dataset, user)

    @classmethod
    async def _ensure_dataset_projected(
        cls, dataset: str, user: Any | None, *, timeout: float | None = None
    ) -> bool:
        instance = cls._legacy_instance()
        actor = user
        if actor is None:
            actor = await instance.dataset_service.get_cognee_user()
        if actor is None:
            return False
        await instance.projection_service.ensure_dataset_projected(dataset, actor, timeout_s=timeout)
        return True

    @classmethod
    async def ensure_global_projected(cls, timeout: float | None = None) -> ProjectionStatus:
        instance = cls._legacy_instance()
        actor = instance._user or await instance.dataset_service.get_cognee_user()
        return await instance._wait_for_projection(instance.GLOBAL_DATASET, actor, timeout_s=timeout)

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
        return await cls._legacy_instance().search_service._search_single_query(
            query,
            datasets,
            user,
            k,
            client_id,
            request_id=request_id,
        )
