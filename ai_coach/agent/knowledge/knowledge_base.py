import asyncio
import inspect
import time
import logging
from hashlib import sha256
from time import monotonic
from typing import Any, ClassVar, Mapping, Callable, Awaitable, TYPE_CHECKING

import cognee
from loguru import logger

from ai_coach.agent.knowledge.base_knowledge_loader import KnowledgeLoader
from ai_coach.agent.knowledge.schemas import KnowledgeSnippet, ProjectionStatus, RebuildResult
from ai_coach.agent.knowledge.utils.chat_queue import ChatProjectionScheduler
from ai_coach.agent.knowledge.cognee_config import CogneeConfig
from ai_coach.agent.knowledge.utils.datasets import DatasetService
from ai_coach.agent.knowledge.utils.projection import ProjectionService
from ai_coach.agent.knowledge.utils.search import SearchService
from ai_coach.agent.knowledge.utils.storage import StorageService
from ai_coach.agent.knowledge.utils.lock_cache import LockCache
from ai_coach.types import MessageRole

from config.app_settings import settings

if TYPE_CHECKING:
    from core.schemas import Profile


class KnowledgeBase:
    """Cognee-backed knowledge storage for the coach agent."""

    _loader: KnowledgeLoader | None = None
    _cognify_locks: LockCache = LockCache()
    _user: Any | None = None
    _warned_missing_user: bool = False
    _PENDING_REBUILDS: ClassVar[set[str]] = set()
    _LAST_REBUILD_RESULT: ClassVar[dict[str, Any]] = {}
    GLOBAL_DATASET: str = settings.COGNEE_GLOBAL_DATASET

    def __init__(self) -> None:
        self._projection_health: dict[str, tuple[ProjectionStatus, str]] = {}
        self.dataset_service = DatasetService()
        self.storage_service = StorageService(self.dataset_service)
        self.dataset_service.set_storage_service(self.storage_service)  # Wire it up
        self.projection_service = ProjectionService(self.dataset_service, self.storage_service)
        self.storage_service.attach_knowledge_base(self)
        self.projection_service.attach_knowledge_base(self)
        self.projection_service.set_waiter(self._wait_for_projection)
        self.search_service = SearchService(self.dataset_service, self.projection_service, knowledge_base=self)
        self.chat_queue_service = ChatProjectionScheduler(self.dataset_service, self)
        self._graph_engine: Any | None = None

    async def _ensure_graph_engine(self) -> None:
        if self._graph_engine is not None:
            return

        graph_engine_getter: Callable[[], Any | Awaitable[Any]] | None = None
        try:
            from cognee.infrastructure.databases.graph import get_graph_engine as graph_engine_getter
        except ModuleNotFoundError:
            try:
                from cognee.modules.graph.methods.get_graph import get_graph_engine as graph_engine_getter
            except ModuleNotFoundError:
                logger.debug("knowledge_graph_engine_unavailable reason=modules_missing")
                return

        try:
            candidate = graph_engine_getter()
            engine = await candidate if inspect.isawaitable(candidate) else candidate
            if engine is not None:
                self.attach_graph_engine(engine)
                logger.debug("knowledge_graph_engine_ready type={}", type(engine))
        except Exception as exc:
            logger.warning(f"knowledge_graph_engine_attach_failed detail={exc}")

    def attach_graph_engine(self, engine: Any | None) -> None:
        self._graph_engine = engine
        self._log_graph_engine_attrs()
        self.dataset_service.set_graph_engine(engine)

    def _log_graph_engine_attrs(self) -> None:
        if self._graph_engine is None:
            return
        attrs = [name for name in dir(self._graph_engine) if not name.startswith("_")]
        sample = attrs[:20]
        logger.debug(
            "knowledge_graph_engine_attrs type={} attrs_sample={} total_attrs={}",
            type(self._graph_engine),
            sample,
            len(attrs),
        )

    async def initialize(self, knowledge_loader: KnowledgeLoader | None = None) -> None:
        CogneeConfig.apply()
        try:
            from cognee.modules.engine.operations.setup import setup as cognee_setup

            await cognee_setup()
        except Exception:
            pass
        self._loader = knowledge_loader
        self._user = await self.dataset_service.get_cognee_user()
        await self._ensure_graph_engine()
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

    async def refresh(self, force: bool = False) -> None:
        from cognee.modules.data.exceptions import DatasetNotFoundError
        from cognee.modules.users.exceptions.exceptions import PermissionDeniedError

        user = await self.dataset_service.get_cognee_user()
        ds = self.dataset_service.alias_for_dataset(self.GLOBAL_DATASET)
        user_ctx = self.dataset_service.to_user_ctx_or_default(user)

        logger.debug(f"knowledge_refresh_start dataset={ds} force={force} user_id={user_ctx.id}")

        await self.dataset_service.ensure_dataset_exists(ds, user_ctx)
        self.dataset_service._PROJECTED_DATASETS.discard(ds)
        if self._loader:
            await self._loader.refresh(force=force)
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

        # Ensure projection is forced if requested, even if loader found duplicates
        # because loader checks HashStore separately from KB state
        if force:
            try:
                self.dataset_service.log_once(
                    logging.INFO, "projection:requested_refresh", dataset=ds, reason="force_refresh"
                )
                await self.projection_service.project_dataset(ds, user_ctx, allow_rebuild=True)
                await self._wait_for_projection(ds, user_ctx, timeout_s=30.0)
            except Exception as exc:
                logger.warning(f"knowledge_refresh:projection_failed detail={exc}")

        counts = await self.dataset_service.get_counts(ds, user_ctx)
        logger.debug(
            f"knowledge_refresh_done dataset={ds} force={force} "
            f"text_rows={counts.get('text_rows')} chunk_rows={counts.get('chunk_rows')} "
            f"graph_nodes={counts.get('graph_nodes')} graph_edges={counts.get('graph_edges')}"
        )

    async def search(
        self, query: str, profile_id: int, k: int | None = None, *, request_id: str | None = None
    ) -> list[KnowledgeSnippet]:
        normalized_query = self.dataset_service._normalize_text(query)
        q_hash = sha256(normalized_query.encode("utf-8")).hexdigest()[:12] if normalized_query else "empty"
        user = await self.dataset_service.get_cognee_user()
        datasets_order = [
            self.dataset_service.chat_dataset_name(profile_id),
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
                        f"projection:empty_after_text dataset={effective} "
                        "reason=no_chunks_or_graph_nodes_after_text_rows"
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
        logger.debug(f"ask.search.start profile_id={profile_id} datasets={dataset_label} q_hash={q_hash}")
        if not searchable_aliases:
            logger.debug(f"kb.search dataset={dataset_label} q_hash={q_hash} hits=0")
            logger.debug(f"ask.search.done profile_id={profile_id} datasets={dataset_label} entries=0")
            return []
        try:
            results = await self.search_service.search(
                query,
                profile_id,
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
        logger.debug(f"ask.search.done profile_id={profile_id} datasets={dataset_label} entries={hits}")
        return results

    async def add_text(
        self,
        text: str,
        *,
        dataset: str | None = None,
        node_set: list[str] | None = None,
        profile_id: int | None = None,
        role: MessageRole | None = None,
        metadata: dict[str, Any] | None = None,
        project: bool = True,
    ) -> None:
        user = await self.dataset_service.get_cognee_user()
        ds = dataset or (
            self.dataset_service.dataset_name(profile_id) if profile_id is not None else self.GLOBAL_DATASET
        )
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

    async def save_client_message(self, text: str, profile_id: int) -> None:
        await self.add_text(
            text,
            dataset=self.dataset_service.chat_dataset_name(profile_id),
            profile_id=profile_id,
            role=MessageRole.CLIENT,
            node_set=[f"profile:{profile_id}", "chat_message"],
            metadata={"channel": "chat"},
            project=False,
        )

    async def save_ai_message(self, text: str, profile_id: int) -> None:
        await self.add_text(
            text,
            dataset=self.dataset_service.chat_dataset_name(profile_id),
            profile_id=profile_id,
            role=MessageRole.AI_COACH,
            node_set=[f"profile:{profile_id}", "chat_message"],
            metadata={"channel": "chat"},
            project=False,
        )

    async def get_message_history(self, profile_id: int, limit: int | None = None) -> list[str]:
        dataset: str = self.dataset_service.alias_for_dataset(self.dataset_service.chat_dataset_name(profile_id))
        user: Any | None = await self.dataset_service.get_cognee_user()
        if user is None:
            if not self._warned_missing_user:
                logger.warning(f"History fetch skipped profile_id={profile_id}: default user unavailable")
                self._warned_missing_user = True
            else:
                logger.debug(f"History fetch skipped profile_id={profile_id}: default user unavailable")
            return []
        user_ctx: Any | None = self.dataset_service.to_user_ctx(user)
        try:
            await self.dataset_service.ensure_dataset_exists(dataset, user_ctx)
        except Exception as exc:
            logger.debug(f"Dataset ensure skipped profile_id={profile_id}: {exc}")
        try:
            data = await self.dataset_service.list_dataset_entries(dataset, user_ctx)
        except Exception:
            logger.info(f"No message history found for profile_id={profile_id}")
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
        force_ingest: bool = False,
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
        digest_sha = self.storage_service.compute_digests(normalized_text, dataset_alias=alias)

        user_ctx = self.dataset_service.to_user_ctx_or_default(actor)
        if user_ctx is None:
            user_ctx = self.dataset_service._bootstrap_user_ctx()

        await self.dataset_service.ensure_dataset_exists(alias, user_ctx)
        rows_before = await self.dataset_service.get_row_count(alias, user=actor)
        metadata_payload = self.dataset_service._infer_metadata_from_text(normalized_text, metadata)
        metadata_payload.setdefault("dataset", alias)

        storage_path = self.storage_service.storage_path_for_sha(digest_sha)
        if storage_path is None:
            logger.debug(f"kb.update dataset={alias} rows_before={rows_before} rows_after={rows_before}")
            return alias, False

        if not force_ingest and await HashStore.contains(alias, digest_sha):
            await HashStore.add(alias, digest_sha, metadata=metadata_payload)
            logger.debug(f"kb_append skipped dataset={alias} digest_sha={digest_sha[:12]} reason=duplicate")
            logger.debug(f"kb.update dataset={alias} rows_before={rows_before} rows_after={rows_before}")
            return alias, False

        storage_path, _ = self.storage_service.ensure_storage_file(
            digest_sha=digest_sha, text=normalized_text, dataset=alias
        )
        if storage_path is None:
            logger.debug(f"kb.update dataset={alias} rows_before={rows_before} rows_after={rows_before}")
            return alias, False

        info: Any | None = None
        try:
            import cognee

            info = await cognee.add(
                normalized_text,
                dataset_name=alias,
                user=user_ctx,
                node_set=list(node_set or []),
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to add dataset entry for {alias}") from exc

        await HashStore.add(alias, digest_sha, metadata=metadata_payload)
        resolved = alias
        identifier = self.dataset_service._extract_dataset_identifier(info)
        if identifier:
            self.dataset_service.register_dataset_identifier(alias, identifier)
            resolved = identifier
        resolved_alias = self.dataset_service.alias_for_dataset(resolved)
        rows_after = await self.dataset_service.get_row_count(resolved_alias, user=actor)
        logger.debug(
            "kb.update rows raw={} alias={} resolved={} rows_before={} rows_after={} digest={} force={}".format(
                dataset,
                alias,
                resolved_alias,
                rows_before,
                rows_after,
                digest_sha[:12],
                force_ingest,
            )
        )
        try:
            self.dataset_service.log_once(logging.INFO, "projection:requested", dataset=resolved_alias, reason="ingest")
            await self.projection_service.project_dataset(resolved_alias, actor, allow_rebuild=False)
            await self._wait_for_projection(resolved_alias, actor, timeout_s=15.0)
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
        timeout_value = timeout_s
        if timeout_value is None:
            timeout_value = kwargs.pop("timeout", None)
        else:
            kwargs.pop("timeout", None)

        if timeout_value is not None:
            try:
                timeout_value = float(timeout_value)
            except (TypeError, ValueError):
                timeout_value = None

        timeout_s = timeout_value
        extra_keys = tuple(kwargs.keys())
        alias = self.dataset_service.alias_for_dataset(dataset)
        if extra_keys:
            logger.debug(f"projection:wait_extra_args dataset={alias} keys={list(extra_keys)}")

        actor = user if user is not None else self._user
        if actor is None:
            try:
                actor = await self.dataset_service.get_cognee_user()
            except Exception:  # noqa: BLE001
                actor = None
        if actor is None:
            self.dataset_service.log_once(
                logging.WARNING,
                "projection:wait_skipped",
                dataset=alias,
                reason="missing_user",
                min_interval=30.0,
            )
            status = ProjectionStatus.TIMEOUT
            self._projection_health[alias] = (status, "missing_user")
            self.projection_service.record_wait_attempts(alias, 0, status)
            return status

        user_ctx = self.dataset_service.to_user_ctx(actor)
        if user_ctx is None:
            try:
                refreshed_actor = await self.dataset_service.get_cognee_user()
            except Exception:  # noqa: BLE001
                refreshed_actor = None
            if refreshed_actor is not None and refreshed_actor is not actor:
                actor = refreshed_actor
                user_ctx = self.dataset_service.to_user_ctx(actor)
        if user_ctx is None:
            self.dataset_service.log_once(
                logging.WARNING,
                "projection:wait_skipped",
                dataset=alias,
                reason="user_context_unavailable",
                min_interval=30.0,
            )
            status = ProjectionStatus.TIMEOUT
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
                alias = self.dataset_service.alias_for_dataset(dataset)
                user_ctx = self.dataset_service.to_user_ctx_or_default(user or self._user)

                from ai_coach.agent.knowledge.utils.hash_store import HashStore

                hashstore_count = await HashStore.count(alias)
                if hashstore_count > 0:
                    self.dataset_service.log_once(
                        logging.WARNING,
                        "projection:mismatch_hashstore_not_empty",
                        dataset=alias,
                        hashstore_count=hashstore_count,
                        reason="no_rows_in_cognee_projection",
                        min_interval=60.0,
                    )
                    logger.debug(f"Triggering reingest for dataset={alias} due to mismatch.")

                    digest_list = await HashStore.list(alias)
                    digests: list[tuple[str, Mapping[str, Any] | None]] = []
                    for digest in digest_list:
                        meta = await HashStore.metadata(alias, digest)
                        digests.append((digest, meta))

                    reingest_result = await self.storage_service.reingest_from_hashstore(
                        alias,
                        user=user_ctx,
                        digests=digests,
                        knowledge_base=self,
                    )

                    if reingest_result.reinserted > 0:
                        logger.info(
                            "Reingest successful for dataset=%s, reinserted=%s. Retrying projection probe.",
                            alias,
                            reingest_result.reinserted,
                        )
                        ready, reason = await self.projection_service.probe(alias, actor)
                        if ready:
                            status = ProjectionStatus.READY
                            self.dataset_service.add_projected_dataset(alias)
                            self._projection_health[alias] = (status, reason)
                            self.projection_service.record_wait_attempts(alias, attempts + 1, status)
                            return status
                        if reason == "no_rows_in_dataset":
                            logger.warning(f"Reingest did not resolve no_rows_in_dataset for dataset={alias}")
                    else:
                        logger.warning(f"Reingest did not reinsert any documents for dataset={alias}")

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
                status = ProjectionStatus.USER_CONTEXT_UNAVAILABLE if reason == "pending" else ProjectionStatus.TIMEOUT
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
        logger.debug(f"knowledge_dataset_rebuild_ready dataset={alias} documents={reinserted} healed={healed_count}")
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

    async def cleanup_profile_datasets(self, profile_id: int) -> dict[str, Any]:
        user = self._user
        if user is None:
            user = await self.dataset_service.get_cognee_user()
        user_ctx = self.dataset_service.to_user_ctx_or_default(user)
        datasets = [
            self.dataset_service.dataset_name(profile_id),
            self.dataset_service.chat_dataset_name(profile_id),
        ]
        seen: set[str] = set()
        results: dict[str, Any] = {}
        for raw in datasets:
            alias = self.dataset_service.alias_for_dataset(raw)
            if not alias or alias in seen:
                continue
            seen.add(alias)
            stats = await self._cleanup_dataset_alias(alias, user_ctx)
            results[alias] = stats
        total_docs = sum(item.get("documents_removed", 0) for item in results.values())
        logger.info(
            "kb_profile_cleanup profile_id={} datasets={} removed_docs={}",
            profile_id,
            ",".join(results.keys()) or "none",
            total_docs,
        )
        return results

    async def _cleanup_dataset_alias(self, alias: str, user_ctx: Any | None) -> dict[str, Any]:
        from ai_coach.agent.knowledge.utils.hash_store import HashStore
        from cognee.modules.data.methods import (
            delete_dataset as delete_dataset_record,
            get_authorized_dataset_by_name,
            get_dataset_data,
        )

        stats: dict[str, Any] = {
            "dataset": alias,
            "dataset_deleted": False,
            "documents_removed": 0,
            "hashes_cleared": 0,
            "storage_deleted": 0,
        }
        issues: list[str] = []
        dataset_obj: Any | None = None
        if user_ctx is None:
            issues.append("missing_user")
        else:
            try:
                dataset_obj = await get_authorized_dataset_by_name(alias, user_ctx, "delete")
            except Exception as exc:  # noqa: BLE001
                issues.append(f"lookup_failed:{exc}")
        if dataset_obj is not None:
            try:
                data_rows = await get_dataset_data(dataset_obj.id)
            except Exception as exc:  # noqa: BLE001
                data_rows = []
                issues.append(f"data_fetch_failed:{exc}")
            for row in data_rows:
                try:
                    await cognee.delete(row.id, dataset_obj.id, mode="hard", user=user_ctx)
                    stats["documents_removed"] += 1
                except Exception as exc:  # noqa: BLE001
                    issues.append(f"doc_delete_failed:{row.id}:{exc}")
            try:
                await delete_dataset_record(dataset_obj)
                stats["dataset_deleted"] = True
            except Exception as exc:  # noqa: BLE001
                issues.append(f"dataset_delete_failed:{exc}")
        elif "missing_user" not in issues:
            issues.append("dataset_missing")

        try:
            digests = sorted(await HashStore.list(alias))
        except Exception as exc:  # noqa: BLE001
            issues.append(f"hash_list_failed:{exc}")
            digests = []
        stats["hashes_cleared"] = len(digests)
        try:
            other_datasets = await HashStore.list_all_datasets()
        except Exception as exc:  # noqa: BLE001
            other_datasets = set()
            issues.append(f"hash_dataset_list_failed:{exc}")
        else:
            other_datasets.discard(alias)
        try:
            await HashStore.clear(alias)
        except Exception as exc:  # noqa: BLE001
            issues.append(f"hash_clear_failed:{exc}")
        try:
            stats["storage_deleted"] = await self.storage_service.drop_dataset_storage(
                alias,
                digests,
                other_datasets=other_datasets,
            )
        except Exception as exc:  # noqa: BLE001
            issues.append(f"storage_cleanup_failed:{exc}")
        self.dataset_service.forget_dataset(alias)
        self._projection_health.pop(alias, None)
        if issues:
            stats["issues"] = issues
        logger.info(
            "kb_dataset_cleanup alias={} docs_removed={} hashes_cleared={} storage_removed={} dataset_deleted={}",
            alias,
            stats["documents_removed"],
            stats["hashes_cleared"],
            stats["storage_deleted"],
            stats["dataset_deleted"],
        )
        return stats

    async def fallback_entries(self, profile_id: int, limit: int = 6) -> list[tuple[str, str]]:
        return await self.search_service.fallback_entries(profile_id, limit)

    def chat_dataset_name(self, profile_id: int) -> str:
        return self.dataset_service.chat_dataset_name(profile_id)

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
            logger.debug(f"cognee_prune.hash_store_cleared datasets={len(datasets)}")
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
    def _health_notes_context(raw: str | None) -> tuple[str | None, bool]:
        if raw is None:
            return None, False
        cleaned = str(raw).strip()
        if not cleaned:
            return None, False
        if cleaned in {"-", "—"}:
            return None, True
        return cleaned, False

    @classmethod
    def _profile_text(cls, profile: "Profile") -> str:
        parts = []
        if profile.gender:
            parts.append(f"gender: {profile.gender}")
        if profile.born_in:
            parts.append(f"born_in: {profile.born_in}")
        if profile.weight:
            parts.append(f"weight: {profile.weight}")
        if profile.workout_experience:
            parts.append(f"workout_experience: {profile.workout_experience}")
        if profile.workout_goals:
            parts.append(f"workout_goals: {profile.workout_goals}")
        health_notes, is_placeholder = cls._health_notes_context(profile.health_notes)
        if health_notes:
            parts.append(f"health_notes: {health_notes}")
        elif is_placeholder:
            parts.append("health_notes: no known injuries or contraindications reported")
        return "profile: " + "; ".join(parts)

    async def sync_profile_dataset(self, profile_id: int) -> bool:
        actor = self._user
        if actor is None:
            try:
                actor = await self.dataset_service.get_cognee_user()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"profile_sync_user_unavailable profile_id={profile_id} detail={exc}")
                actor = None
        if actor is None:
            logger.warning(f"profile_sync_skipped profile_id={profile_id} reason=missing_user")
            return False
        search_service = getattr(self, "search_service", None)
        if search_service is None:
            logger.warning(f"profile_sync_skipped profile_id={profile_id} reason=missing_search_service")
            return False
        try:
            indexed = await search_service._ensure_profile_indexed(profile_id, actor)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"profile_sync_failed profile_id={profile_id} detail={exc}")
            return False
        logger.info(f"profile_sync_completed profile_id={profile_id} indexed={indexed}")
        return bool(indexed)
