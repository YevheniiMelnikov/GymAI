import asyncio
import logging
from time import monotonic
from enum import Enum
from hashlib import sha256
from typing import Any, Awaitable, Iterable, Mapping, Sequence, cast, Literal, Optional, TYPE_CHECKING

try:
    from cognee.modules.search.types import SearchType
    import cognee
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    cognee = None  # type: ignore[assignment]

    class SearchType(str, Enum):
        GRAPH_COMPLETION_CONTEXT_EXTENSION = "GRAPH_COMPLETION_CONTEXT_EXTENSION"

        @classmethod
        def _missing_(cls, value: object) -> "SearchType":
            return cls.GRAPH_COMPLETION_CONTEXT_EXTENSION

        def __str__(self) -> str:
            return self.value

        def __repr__(self) -> str:
            return f"{type(self).__name__}.{self.name}"


from loguru import logger

from ai_coach.agent.knowledge.schemas import KnowledgeSnippet, ProjectionStatus
from ai_coach.agent.knowledge.utils.datasets import DatasetService
from ai_coach.agent.knowledge.utils.projection import ProjectionService
from ai_coach.agent.knowledge.utils.memify_scheduler import schedule_profile_memify
from ai_coach.exceptions import AgentExecutionAborted
from config.app_settings import settings
from core.utils.redis_lock import get_redis_client


if TYPE_CHECKING:
    from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase


def _resolve_search_type(mode: str | SearchType | None) -> SearchType:
    if isinstance(mode, SearchType):
        return mode
    candidate = (mode or "").strip()
    if not candidate:
        return SearchType.GRAPH_COMPLETION_CONTEXT_EXTENSION
    try:
        return SearchType(candidate)
    except ValueError:
        upper = candidate.upper()
        try:
            return SearchType[upper]
        except KeyError:
            return SearchType.GRAPH_COMPLETION_CONTEXT_EXTENSION


class SearchService:
    def __init__(
        self,
        dataset_service: DatasetService,
        projection_service: ProjectionService,
        *,
        knowledge_base: Optional["KnowledgeBase"] = None,
    ):
        self.dataset_service = dataset_service
        self.projection_service = projection_service
        self._knowledge_base: Optional["KnowledgeBase"] = knowledge_base
        self._search_type_default = _resolve_search_type(getattr(settings, "COGNEE_SEARCH_MODE", None))
        self._memify_delay = max(float(getattr(settings, "AI_COACH_MEMIFY_DELAY_SECONDS", 3600.0)), 0.0)

    def _require_kb(self) -> "KnowledgeBase":
        if self._knowledge_base is None:
            raise RuntimeError("knowledge_base_unavailable")
        return self._knowledge_base

    async def _apply_session_context(self, user_ctx: Any | None, profile_id: int) -> None:
        if user_ctx is None:
            return
        try:
            from cognee.modules.retrieval.utils.session_cache import set_session_user_context_variable
        except Exception as exc:  # noqa: BLE001
            logger.debug("cognee_session_context_unavailable profile_id={} detail={}", profile_id, exc)
            return
        try:
            import inspect

            if inspect.iscoroutinefunction(set_session_user_context_variable):
                await set_session_user_context_variable(user_ctx)
            else:
                set_session_user_context_variable(user_ctx)
        except Exception as exc:  # noqa: BLE001
            logger.debug("cognee_session_context_failed profile_id={} detail={}", profile_id, exc)

    def _ensure_session_cache_available(self, profile_id: int) -> None:
        try:
            from cognee.infrastructure.databases.cache.get_cache_engine import get_cache_engine
        except Exception as exc:  # noqa: BLE001
            logger.error("knowledge_session_cache_unavailable profile_id={} detail={}", profile_id, exc)
            raise AgentExecutionAborted("knowledge_base_unavailable", reason="knowledge_base_unavailable") from exc
        cache = get_cache_engine(lock_key=f"chat_session:{profile_id}")
        if cache is None:
            logger.error("knowledge_session_cache_unavailable profile_id={} detail=cache_engine_none", profile_id)
            raise AgentExecutionAborted("knowledge_base_unavailable", reason="knowledge_base_unavailable")

    def _build_candidate_aliases(self, datasets: Sequence[str] | None, profile_id: int) -> list[str]:
        candidate_aliases: list[str] = []
        if datasets is not None:
            for name in datasets:
                alias = self.dataset_service.alias_for_dataset(name)
                if alias not in candidate_aliases:
                    candidate_aliases.append(alias)
            return candidate_aliases

        candidate_aliases.extend(
            [
                self.dataset_service.alias_for_dataset(self.dataset_service.dataset_name(profile_id)),
                self.dataset_service.alias_for_dataset(self.dataset_service.chat_dataset_name(profile_id)),
            ]
        )
        global_alias_default = self.dataset_service.alias_for(self.dataset_service.GLOBAL_DATASET)
        if global_alias_default not in candidate_aliases:
            candidate_aliases.append(global_alias_default)
        return candidate_aliases

    async def _ensure_global_dataset_ready(
        self,
        candidate_aliases: list[str],
        actor: Any | None,
        profile_id: int,
        rid_value: str,
    ) -> tuple[list[str], bool]:
        global_alias = self.dataset_service.alias_for(self.dataset_service.GLOBAL_DATASET)
        include_global = global_alias in candidate_aliases
        global_ready = not include_global or global_alias in self.dataset_service._PROJECTED_DATASETS
        global_unavailable = False

        if include_global and not global_ready:
            status = await self.projection_service.ensure_dataset_projected(
                self.dataset_service.GLOBAL_DATASET,
                actor,
                timeout_s=0.3,
            )
            if status in (ProjectionStatus.READY, ProjectionStatus.READY_EMPTY):
                self.dataset_service.add_projected_dataset(global_alias)
                global_ready = True
            else:
                global_unavailable = True
                candidate_aliases = [alias for alias in candidate_aliases if alias != global_alias]
                self.dataset_service.log_once(
                    logging.INFO,
                    "knowledge_search_global_pending",
                    throttle_key=f"projection:{global_alias}:search_pending",
                    profile_id=profile_id,
                    rid=rid_value,
                )

        return candidate_aliases, global_unavailable

    async def _resolve_datasets(
        self,
        candidate_aliases: list[str],
        user_ctx: Any | None,
        profile_id: int,
    ) -> list[str]:
        resolved_datasets: list[str] = []
        for alias in candidate_aliases:
            resolved = self.dataset_service.alias_for_dataset(alias)
            try:
                await self.dataset_service.ensure_dataset_exists(resolved, user_ctx)
            except Exception as ensure_exc:
                logger.debug(
                    "knowledge_dataset_ensure_failed profile_id={} dataset={} detail={}",
                    profile_id,
                    resolved,
                    ensure_exc,
                )
            resolved_datasets.append(resolved)
        return resolved_datasets

    async def _run_queries(
        self,
        queries: Sequence[str],
        resolved_datasets: list[str],
        actor: Any | None,
        k: int | None,
        profile_id: int,
        request_id: str | None,
        session_id: str,
    ) -> list[KnowledgeSnippet]:
        aggregated: list[KnowledgeSnippet] = []
        seen: set[str] = set()
        for variant in queries:
            snippets = await self._search_single_query(
                variant,
                resolved_datasets,
                actor,
                k,
                profile_id,
                query_type=self._search_type_default,
                request_id=request_id,
                session_id=session_id,
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
        return aggregated

    async def search(
        self,
        query: str,
        profile_id: int,
        k: int | None = None,
        *,
        request_id: str | None = None,
        datasets: Sequence[str] | None = None,
        user: Any | None = None,
    ) -> list[KnowledgeSnippet]:
        started_at = monotonic()
        if cognee is None:
            logger.warning("knowledge_search_skipped profile_id={} reason=cognee_missing", profile_id)
            self._log_search_completion(profile_id, request_id or "na", "none", 0, started_at)
            return []

        normalized = query.strip()
        if not normalized:
            logger.debug(f"Knowledge search skipped profile_id={profile_id}: empty query")
            self._log_search_completion(profile_id, request_id or "na", "none", 0, started_at)
            return []
        rid_value = request_id or "na"
        actor = user if user is not None else await self.dataset_service.get_cognee_user()
        await self._schedule_profile_sync(profile_id)
        user_ctx = self.dataset_service.to_user_ctx(actor)
        session_id = self.dataset_service.session_id_for_profile(profile_id)
        await self._apply_session_context(user_ctx, profile_id)
        self._ensure_session_cache_available(profile_id)
        candidate_aliases = self._build_candidate_aliases(datasets, profile_id)
        candidate_aliases, global_unavailable = await self._ensure_global_dataset_ready(
            candidate_aliases,
            actor,
            profile_id,
            rid_value,
        )

        if not candidate_aliases:
            logger.debug(f"knowledge_search_skipped profile_id={profile_id} rid={rid_value} reason=no_datasets")
            self._log_search_completion(profile_id, rid_value, "none", 0, started_at)
            return []

        resolved_datasets = await self._resolve_datasets(candidate_aliases, user_ctx, profile_id)

        try:
            base_hash = sha256(normalized.encode()).hexdigest()[:12]
            datasets_hint = ",".join(resolved_datasets)
            top_k_label = k if k is not None else "default"
            logger.debug(
                f"knowledge_search_start profile_id={profile_id} rid={rid_value} query_hash={base_hash} "
                f"datasets={datasets_hint} top_k={top_k_label} global_unavailable={global_unavailable}"
            )

            queries = self._expanded_queries(normalized)
            if len(queries) > 1:
                logger.debug(
                    f"knowledge_search_expanded profile_id={profile_id} rid={rid_value} "
                    f"variants={len(queries)} base_query_hash={base_hash}"
                )

            aggregated = await self._run_queries(
                queries,
                resolved_datasets,
                actor,
                k,
                profile_id,
                request_id,
                session_id,
            )

            await self._maybe_schedule_memify(profile_id)
            if k is not None:
                aggregated = aggregated[:k]
            if not aggregated:
                self.dataset_service.log_once(
                    logging.INFO,
                    "search:empty",
                    profile_id=profile_id,
                    rid=rid_value,
                    datasets=datasets_hint,
                    min_interval=60.0,
                )
                logger.debug(f"knowledge_search_empty profile_id={profile_id} rid={rid_value} datasets={datasets_hint}")
            self._log_search_completion(profile_id, rid_value, datasets_hint, len(aggregated), started_at)
            return aggregated
        except asyncio.CancelledError:
            cancel_hint = ",".join(resolved_datasets) if resolved_datasets else ",".join(candidate_aliases)
            self._log_search_completion(profile_id, rid_value, cancel_hint or "none", 0, started_at)
            raise

    async def _search_single_query(
        self,
        query: str,
        datasets: list[str],
        user: Any | None,
        k: int | None,
        profile_id: int,
        *,
        query_type: SearchType = SearchType.GRAPH_COMPLETION_CONTEXT_EXTENSION,
        request_id: str | None = None,
        session_id: str,
    ) -> list[KnowledgeSnippet]:
        if user is None:
            logger.warning(f"knowledge_search_skipped profile_id={profile_id}: user context unavailable")
            return []
        query_hash = sha256(query.encode()).hexdigest()[:12]
        skipped_aliases: list[str] = []
        rid_value = request_id or "na"
        user_ctx = self.dataset_service.to_user_ctx(user)

        async def _search_targets(targets: list[str], session: str | None) -> list[str]:
            params: dict[str, Any] = {
                "datasets": targets,
                "user": user_ctx,
                "query_type": query_type,
            }
            if session:
                params["session_id"] = session
            if k is not None:
                params["top_k"] = k
            return await cognee.search(query, **params)

        ready_datasets: list[str] = []
        for dataset in datasets:
            target = (dataset or "").strip() or dataset
            alias = self.dataset_service.alias_for_dataset(dataset)
            try:
                counts = await self.dataset_service.get_counts(alias, user)
            except Exception as exc:
                logger.debug(f"projection:count_unavailable dataset={alias} detail={exc}")
                fallback_rows = await self.dataset_service.get_row_count(alias, user)
                counts = {"text_rows": fallback_rows, "chunk_rows": 0, "graph_nodes": 0, "graph_edges": 0}
            text_rows = int(counts.get("text_rows") or 0)
            chunk_rows = int(counts.get("chunk_rows") or 0)
            legacy_rows = 0
            if target and target != alias:
                legacy_rows = await self.dataset_service.get_row_count(target, user)
                if legacy_rows > 0 and text_rows <= 0 and chunk_rows <= 0:
                    logger.debug(f"projection.legacy_rows dataset={target} alias={alias} legacy_rows={legacy_rows}")
            has_rows = (text_rows > 0 or chunk_rows > 0) or legacy_rows > 0
            if not has_rows:
                self.dataset_service.log_once(
                    logging.INFO,
                    "projection:skip_no_rows",
                    dataset=alias,
                    stage="search",
                    min_interval=120.0,
                )
                logger.debug(f"projection.skip_no_rows dataset={alias} stage=search")
                skipped_aliases.append(alias)
                continue
            try:
                await self.dataset_service.ensure_dataset_exists(alias, user_ctx)
            except Exception as ensure_exc:
                logger.debug(
                    f"knowledge_dataset_ensure_failed profile_id={profile_id} dataset={alias} detail={ensure_exc}"
                )
                skipped_aliases.append(alias)
                continue
            if alias in self.dataset_service._PROJECTED_DATASETS:
                ready_datasets.append(target)
                continue
            try:
                status = await self.projection_service.ensure_dataset_projected(alias, user, timeout_s=2.0)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"knowledge_projection_ensure_failed dataset={alias} detail={exc}")
                skipped_aliases.append(alias)
                continue
            if status in (ProjectionStatus.READY, ProjectionStatus.READY_EMPTY):
                ready_datasets.append(target)
            else:
                skipped_aliases.append(alias)

        if not ready_datasets:
            if skipped_aliases:
                self.dataset_service.log_once(
                    logging.DEBUG,
                    "search:skipped",
                    profile_id=profile_id,
                    rid=rid_value,
                    datasets=",".join(skipped_aliases),
                    min_interval=5.0,
                )
            fallback_raw = await self._fallback_dataset_entries(datasets, user, top_k=k)
            if fallback_raw:
                primary_source = skipped_aliases[0] if skipped_aliases else datasets[0]
                primary_alias = self.dataset_service.alias_for_dataset(primary_source)
                snippets = [
                    KnowledgeSnippet(text=value, dataset=primary_alias, kind="document")
                    for value in fallback_raw
                    if value.strip()
                ]
                return snippets[:k] if k is not None else snippets
            self.dataset_service.log_once(
                logging.INFO,
                "search:empty",
                profile_id=profile_id,
                rid=rid_value,
                datasets=",".join(datasets),
                min_interval=60.0,
            )
            logger.debug(
                f"knowledge_search_empty profile_id={profile_id} rid={rid_value} datasets={','.join(datasets)}"
            )
            return []

        for dataset_name in ready_datasets:
            alias_name = self.dataset_service.alias_for_dataset(dataset_name)
            logger.debug(f"kb.search alias={alias_name} target={dataset_name} q_hash={query_hash}")

        try:
            results = await _search_targets(ready_datasets, session_id)
            logger.debug(
                f"knowledge_search_ok profile_id={profile_id} rid={rid_value} "
                f"query_hash={query_hash} results={len(results)}"
            )
            if not results:
                await asyncio.sleep(0.25)
                retry = await _search_targets(ready_datasets, None)
                if retry:
                    logger.info(
                        f"knowledge_search_retry_after_empty profile_id={profile_id} rid={rid_value} "
                        f"query_hash={query_hash} results={len(retry)}"
                    )
                    results = retry
            snippets = await self._build_snippets(results, ready_datasets, user)
            if snippets:
                per_alias: dict[str, int] = {}
                for snippet in snippets:
                    alias = (snippet.dataset or "").strip() or "unknown"
                    per_alias[alias] = per_alias.get(alias, 0) + 1
                for alias, count in per_alias.items():
                    logger.debug(f"kb.search.hits alias={alias} count={count}")
            return snippets
        except Exception as exc:
            ready_aliases = [self.dataset_service.alias_for_dataset(ds) for ds in ready_datasets]
            kb = self._knowledge_base
            if kb is not None and kb._is_graph_missing_error(exc):
                for alias in ready_aliases:
                    self.dataset_service._PROJECTED_DATASETS.discard(alias)
                logger.info(
                    f"knowledge_dataset_search_skipped dataset={','.join(ready_aliases)} rid={rid_value} "
                    f"reason=projection_incomplete detail={exc}"
                )
                return []
            logger.warning(
                f"knowledge_search_failed profile_id={profile_id} rid={rid_value} query_hash={query_hash} detail={exc}"
            )
            logger.debug(f"kb.search.fail detail={exc}")
            return []

    async def _build_snippets(
        self, items: Iterable[Any], datasets: Sequence[str], user: Any | None
    ) -> list[KnowledgeSnippet]:
        from ai_coach.agent.knowledge.utils.storage import StorageService

        prepared: list[tuple[str, str, str | None, Mapping[str, Any] | None]] = []
        for raw in items:
            text, dataset_hint, metadata = self._extract_search_item(raw)
            if not text:
                continue
            if metadata is not None and not isinstance(metadata, Mapping):
                metadata = self.dataset_service._coerce_metadata(metadata)
            normalized_text = self.dataset_service._normalize_text(text)
            if not normalized_text:
                continue
            prepared.append((text, normalized_text, dataset_hint, metadata))
        if not prepared:
            return []

        digests_sha = [
            StorageService.compute_digests(normalized_text, dataset_alias=None) for _, normalized_text, _, _ in prepared
        ]
        dataset_list = list(datasets)
        metadata_results: list[tuple[str | None, Mapping[str, Any] | None]] = [(None, None)] * len(prepared)
        pending: list[int] = []

        for index, ((_, _, dataset_hint, metadata), _) in enumerate(zip(prepared, digests_sha, strict=False)):
            if metadata is not None:
                meta_dict = dict(metadata)
                dataset_name = self.dataset_service._extract_dataset_key(meta_dict) or dataset_hint
                alias = self.dataset_service.resolve_dataset_alias(dataset_name) if dataset_name else None
                if alias:
                    meta_dict.setdefault("dataset", alias)
                metadata_results[index] = (alias, meta_dict)
            else:
                metadata_results[index] = (dataset_hint, None)
                pending.append(index)

        if pending:
            lookups = await asyncio.gather(*(self._collect_metadata(digests_sha[i], datasets) for i in pending))
            for slot, (dataset_name, meta) in zip(pending, lookups, strict=False):
                alias_source = dataset_name or prepared[slot][2]
                fallback_dataset = alias_source or (dataset_list[0] if dataset_list else "")
                alias = self.dataset_service.alias_for_dataset(fallback_dataset) if fallback_dataset else None
                if meta:
                    meta_dict = dict(meta)
                else:
                    meta_dict = {}
                if alias:
                    meta_dict.setdefault("dataset", alias)
                metadata_results[slot] = (alias, meta_dict or None)

        snippets: list[KnowledgeSnippet] = []
        add_tasks: list[Awaitable[None]] = []
        for index, ((text, normalized_text, dataset_hint, _), (resolved_dataset, payload)) in enumerate(
            zip(prepared, metadata_results, strict=False)
        ):
            alias_source = resolved_dataset or dataset_hint or (dataset_list[0] if dataset_list else "")
            dataset_alias = self.dataset_service.alias_for_dataset(alias_source) if alias_source else None
            if dataset_alias is None and dataset_list:
                dataset_alias = self.dataset_service.alias_for_dataset(dataset_list[0])
            extra_payload: dict[str, Any] = dict(payload) if payload else {}
            if dataset_alias:
                extra_payload.setdefault("dataset", dataset_alias)
            payload_dict = self.dataset_service._infer_metadata_from_text(normalized_text, extra_payload)
            digest_base = digests_sha[index]
            digest_sha = (
                StorageService.compute_digests(normalized_text, dataset_alias=dataset_alias)
                if dataset_alias
                else digest_base
            )
            metadata_payload = StorageService.augment_metadata(
                payload_dict,
                dataset_alias,
                digest_sha=digest_sha,
            )
            if dataset_alias:
                from ai_coach.agent.knowledge.utils.hash_store import HashStore

                add_tasks.append(HashStore.add(dataset_alias, digest_sha, metadata=metadata_payload))
            else:
                metadata_payload.pop("dataset", None)

            kind = self._resolve_snippet_kind(metadata_payload, text)
            if kind == "message":
                kind = "note"

            dataset_value = str(metadata_payload.get("dataset") or dataset_alias or "").strip() or None
            if kind in {"document", "note"}:
                snippet_kind = cast(Literal["document", "note"], kind)
            else:
                snippet_kind = "unknown"
            snippets.append(KnowledgeSnippet(text=text, dataset=dataset_value, kind=snippet_kind))

        if add_tasks:
            await asyncio.gather(*add_tasks)
        return snippets

    def _extract_search_item(self, raw: Any) -> tuple[str, str | None, Mapping[str, Any] | None]:
        from dataclasses import asdict, is_dataclass

        if raw is None:
            return "", None, None
        if is_dataclass(raw):
            return self._extract_search_item(asdict(raw))
        if isinstance(raw, Mapping):
            text_value = raw.get("text", "")
            text = str(text_value or "").strip()
            metadata = self.dataset_service._coerce_metadata(raw.get("metadata"))
            dataset_hint = self.dataset_service._extract_dataset_key(metadata)
            if dataset_hint is None:
                dataset_hint = self.dataset_service._extract_dataset_key(raw)
            if dataset_hint:
                dataset_hint = self.dataset_service.resolve_dataset_alias(dataset_hint)
            return text, dataset_hint, metadata
        text_attr = getattr(raw, "text", None)
        if text_attr is None and hasattr(raw, "content"):
            text_attr = getattr(raw, "content")
        text = str(text_attr or raw).strip()
        metadata = self.dataset_service._coerce_metadata(getattr(raw, "metadata", None))
        dataset_hint = self.dataset_service._extract_dataset_key(metadata)
        if dataset_hint is None:
            raw_payload: Mapping[str, Any] | None = None
            if isinstance(raw, Mapping):
                raw_payload = raw
            else:
                try:
                    raw_payload = vars(raw)  # type: ignore[var-annotated]
                except TypeError:
                    raw_payload = None
            dataset_hint = self.dataset_service._extract_dataset_key(raw_payload)
        if dataset_hint:
            dataset_hint = self.dataset_service.resolve_dataset_alias(dataset_hint)
        return text, dataset_hint, metadata

    async def _collect_metadata(
        self, digest: str, datasets: Sequence[str]
    ) -> tuple[str | None, Mapping[str, Any] | None]:
        from ai_coach.agent.knowledge.utils.hash_store import HashStore

        if not datasets:
            return None, None
        lookups = await asyncio.gather(
            *(HashStore.metadata(self.dataset_service.alias_for_dataset(dataset), digest) for dataset in datasets)
        )
        for dataset, meta in zip(datasets, lookups, strict=False):
            alias = self.dataset_service.alias_for_dataset(dataset)
            if meta:
                enriched = dict(meta)
                enriched.setdefault("dataset", alias)
                return alias, enriched
        fallback = self.dataset_service.alias_for_dataset(datasets[0]) if datasets else None
        return fallback, None

    async def _fallback_dataset_entries(
        self, datasets: Sequence[str], user_ctx: Any | None, *, top_k: int | None
    ) -> list[tuple[str, str]]:
        from ai_coach.agent.knowledge.utils.storage import StorageService
        from ai_coach.agent.knowledge.utils.hash_store import HashStore

        collected: list[tuple[str, str]] = []
        limit = top_k or 6
        for dataset in datasets:
            rows = await self.dataset_service.list_dataset_entries(dataset, user_ctx)
            if not rows:
                continue
            alias = self.dataset_service.alias_for_dataset(dataset)
            for row in rows:
                normalized = self.dataset_service._normalize_text(row.text)
                if not normalized:
                    continue
                metadata = dict(row.metadata) if isinstance(row.metadata, Mapping) else {}
                metadata.setdefault("dataset", alias)
                metadata_dict = self.dataset_service._infer_metadata_from_text(normalized, metadata)
                dig_sha = StorageService.compute_digests(normalized, dataset_alias=alias)
                ensured_metadata = StorageService.augment_metadata(metadata_dict, alias, digest_sha=dig_sha)
                StorageService.ensure_storage_file(
                    digest_sha=dig_sha,
                    text=normalized,
                    dataset=alias,
                )
                await HashStore.add(alias, dig_sha, metadata=ensured_metadata)
                if ensured_metadata.get("kind") == "message":
                    continue
                collected.append((normalized, alias))
                if len(collected) >= limit:
                    return collected
        return collected

    async def fallback_entries(self, profile_id: int, limit: int = 6) -> list[tuple[str, str]]:
        user = await self.dataset_service.get_cognee_user()
        aliases = [
            self.dataset_service.dataset_name(profile_id),
            self.dataset_service.chat_dataset_name(profile_id),
            self.dataset_service.GLOBAL_DATASET,
        ]
        datasets = [self.dataset_service.alias_for_dataset(alias) for alias in aliases]
        user_ctx = self.dataset_service.to_user_ctx(user)
        return await self._fallback_dataset_entries(datasets, user_ctx, top_k=limit)

    async def _warm_up_datasets(self, datasets: list[str], user: Any | None) -> None:
        kb = self._knowledge_base
        if kb is None:
            logger.debug("knowledge_dataset_warmup_skipped reason=knowledge_base_unavailable")
            return
        for dataset in datasets:
            try:
                await kb._process_dataset(dataset, user)
            except Exception as exc:
                logger.warning(f"knowledge_dataset_warmup_failed dataset={dataset} detail={exc}")

    async def _maybe_schedule_memify(self, profile_id: int) -> None:
        if cognee is None or not hasattr(cognee, "memify"):
            logger.debug("knowledge_memify_schedule_skipped profile_id={} reason=memify_missing", profile_id)
            return
        datasets = [
            self.dataset_service.alias_for_dataset(self.dataset_service.dataset_name(profile_id)),
            self.dataset_service.alias_for_dataset(self.dataset_service.chat_dataset_name(profile_id)),
        ]
        dataset_label = ",".join(datasets)
        scheduled = await schedule_profile_memify(profile_id, reason="paid_flow", delay_s=self._memify_delay)
        if scheduled:
            logger.info(
                "knowledge_memify_scheduled profile_id={} datasets={} delay_s={}",
                profile_id,
                dataset_label,
                self._memify_delay,
            )
        else:
            logger.debug(
                "knowledge_memify_schedule_declined profile_id={} datasets={} reason=dedupe_or_error",
                profile_id,
                dataset_label,
            )

    def _log_search_completion(
        self,
        profile_id: int,
        rid_value: str,
        datasets_hint: str,
        hits: int,
        started_at: float,
    ) -> None:
        elapsed = monotonic() - started_at
        logger.debug(
            "knowledge_search_finish profile_id={} rid={} datasets={} hits={} elapsed_s={:.2f}",
            profile_id,
            rid_value,
            datasets_hint or "none",
            hits,
            elapsed,
        )

    def _expanded_queries(self, query: str) -> list[str]:
        return [query]

    async def _schedule_profile_sync(self, profile_id: int) -> None:
        key = f"ai_coach:profile_sync:{profile_id}"
        try:
            client = get_redis_client()
            if not await client.set(key, "1", nx=True, ex=600):
                return
        except Exception as exc:  # noqa: BLE001
            logger.debug("profile_sync_dedupe_failed profile_id={} detail={}", profile_id, exc)
            return
        try:
            from core.tasks.ai_coach.maintenance import sync_profile_knowledge

            getattr(sync_profile_knowledge, "delay")(profile_id, reason="search")
            logger.info("profile_sync_enqueued profile_id={} reason=search", profile_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("profile_sync_enqueue_failed profile_id={} detail={}", profile_id, exc)

    def _resolve_snippet_kind(self, metadata: Mapping[str, Any] | None, text: str) -> str:
        if metadata:
            kind_value = str(metadata.get("kind", "")).lower()
            if kind_value in {"document", "note"}:
                return kind_value
            if kind_value == "message":
                return "message"
            if kind_value:
                return "unknown"
        inferred = self.dataset_service._infer_metadata_from_text(text)
        if inferred and inferred.get("kind") == "message":
            return "message"
        return "document"

    async def _ensure_profile_indexed(self, profile_id: int, user: Any | None) -> bool:
        from core.services import APIService

        try:
            profile = await APIService.profile.get_profile(profile_id)
        except Exception as e:
            logger.warning(f"Failed to fetch profile id={profile_id}: {e}")
            return False
        if not profile:
            return False
        kb = self._knowledge_base
        if kb is None:
            logger.debug(f"knowledge_profile_index_skip profile_id={profile_id} reason=knowledge_base_unavailable")
            return False
        text = kb._profile_text(profile)
        dataset = self.dataset_service.dataset_name(profile_id)
        dataset, created = await kb.update_dataset(
            text,
            dataset,
            user,
            node_set=["profile", f"profile:{profile_id}"],
            metadata={"kind": "document", "source": "profile"},
        )
        if created:
            await kb._process_dataset(dataset, user)
        return bool(created)
