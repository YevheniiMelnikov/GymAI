import asyncio
import inspect
import logging
import os
import random
import time
from dataclasses import asdict, dataclass, is_dataclass
from hashlib import md5, sha256
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
    _LEGACY_CLIENT_PREFIX: str = "client_"
    _PROJECTION_CHECK_QUERY: str = "__knowledge_projection_health__"
    _PROJECTION_BACKOFF_SECONDS: tuple[float, ...] = (0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 12.0)

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
        cls._PROJECTED_DATASETS.clear()
        try:
            await cls.refresh()
        except Exception as e:
            logger.warning(f"Knowledge refresh skipped: {e}")
        timeout = float(settings.AI_COACH_GLOBAL_PROJECTION_TIMEOUT)
        try:
            await cls.ensure_global_projected(timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - diagnostics only
            logger.warning(f"Knowledge global projection wait failed: {exc}")

    @classmethod
    async def refresh(cls) -> None:
        """Re-cognify global dataset and refresh loader if available."""
        user = await cls._get_cognee_user()
        ds = cls._resolve_dataset_alias(cls.GLOBAL_DATASET)
        await cls._ensure_dataset_exists(ds, user)
        cls._PROJECTED_DATASETS.discard(cls._alias_for_dataset(ds))
        if cls._loader:
            await cls._loader.refresh()
        user_ns = cls._to_user_or_none(user)
        target = ds
        try:
            dataset_id = await cls._get_dataset_id(ds, user, user_ns)
        except ProjectionProbeError:
            dataset_id = None
        if dataset_id:
            target = dataset_id
        try:
            await cognee.cognify(datasets=[target], user=user_ns)  # pyrefly: ignore[bad-argument-type]
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
                f"projection:{dataset}:ensure_missing",
                logging.DEBUG,
                f"knowledge_projection_dataset_missing dataset={dataset} detail={exc}",
            )
        user_ns = cls._to_user_or_none(user)
        ready = await cls._wait_for_projection(dataset, user_ns, user=user, timeout=timeout)
        if ready:
            cls._PROJECTED_DATASETS.add(cls._alias_for_dataset(dataset))
            return True

        if user is not None:
            try:
                entries = await cls._list_dataset_entries(dataset, user)
            except Exception as exc:  # noqa: BLE001 - diagnostics only
                cls._log_once(
                    f"projection:{dataset}:ensure_list_failed",
                    logging.DEBUG,
                    f"knowledge_projection_pending dataset={dataset} reason=list_entries_failed detail={exc}",
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
                        retry_ready = await cls._wait_for_projection(
                            dataset,
                            user_ns,
                            user=user,
                            timeout=retry_timeout,
                        )
                        if retry_ready:
                            alias = cls._alias_for_dataset(dataset)
                            cls._PROJECTED_DATASETS.add(alias)
                            return True

        cls._log_once(
            f"projection:{dataset}:deferred",
            logging.INFO,
            f"knowledge_projection_deferred dataset={dataset}",
        )
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
            from cognee.api.v1.prune import prune as cognee_prune  # pyrefly: ignore[import-error]
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
        if not normalized_text:
            return dataset, False
        digest_sha, digest_md5 = cls._compute_digests(normalized_text)
        payload = normalized_text.encode("utf-8")
        ds_name = cls._resolve_dataset_alias(dataset)
        await cls._ensure_dataset_exists(ds_name, user)
        storage_path, created_file = cls._ensure_storage_file(digest_md5, normalized_text, dataset=ds_name)
        if created_file:
            logger.debug(
                f"kb_write start dataset={ds_name} digest_sha={digest_sha[:12]} digest_md5={digest_md5[:12]} "
                f"path={storage_path} bytes={len(payload)}"
            )
        metadata_payload = cls._augment_metadata(metadata, ds_name, digest_sha=digest_sha, digest_md5=digest_md5)
        if await HashStore.contains(ds_name, digest_sha):
            await HashStore.add(ds_name, digest_sha, metadata=metadata_payload)
            logger.debug(f"kb_append skipped dataset={ds_name} digest_sha={digest_sha[:12]} reason=duplicate")
            return ds_name, False

        attempts = 0
        info: Any | None = None
        while attempts < 2:
            try:
                info = await _safe_add(
                    normalized_text,
                    dataset_name=ds_name,
                    user=cls._to_user_or_none(user),  # pyrefly: ignore[bad-argument-type]
                    node_set=node_set,
                )
            except FileNotFoundError as exc:
                attempts += 1
                missing_path = getattr(exc, "filename", None) or str(exc)
                logger.debug(
                    f"knowledge_dataset_retry_missing_file dataset={ds_name} digest_md5={digest_md5[:12]} "
                    f"attempt={attempts} missing={missing_path}"
                )
                storage_path, created_file = cls._ensure_storage_file(digest_md5, normalized_text, dataset=ds_name)
                if created_file:
                    logger.debug(
                        f"kb_write start dataset={ds_name} digest_sha={digest_sha[:12]} digest_md5={digest_md5[:12]} "
                        f"path={storage_path} bytes={len(payload)}"
                    )
                    metadata_payload = cls._augment_metadata(
                        metadata, ds_name, digest_sha=digest_sha, digest_md5=digest_md5
                    )
                if attempts >= 2:
                    raise
                continue
            except (DatasetNotFoundError, PermissionDeniedError):
                raise
            break

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
        logger.debug(
            f"kb_append ok dataset={resolved} digest_sha={digest_sha[:12]} digest_md5={digest_md5[:12]} "
            f"path={storage_path}"
        )
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
        request_id_str = request_id or "na"
        global_alias = cls._alias_for_dataset(cls._resolve_dataset_alias(cls.GLOBAL_DATASET))
        global_ready = True
        if global_alias not in cls._PROJECTED_DATASETS:
            ready = await cls.ensure_global_projected(timeout=float(settings.AI_COACH_GLOBAL_PROJECTION_TIMEOUT))
            if ready:
                cls._PROJECTED_DATASETS.add(global_alias)
            else:
                global_ready = False
                cls._log_once(
                    f"projection:{global_alias}:search_pending",
                    logging.INFO,
                    f"knowledge_search_global_pending client_id={client_id} request_id={request_id_str}",
                )
        user = await cls._get_cognee_user()
        await cls._ensure_profile_indexed(client_id, user)
        datasets = [cls._dataset_name(client_id)]
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
            f"knowledge_search_start client_id={client_id} request_id={request_id_str} query_hash={base_hash} "
            f"datasets={datasets_hint} top_k={top_k_label}"
        )

        queries = cls._expanded_queries(normalized)
        if len(queries) > 1:
            logger.debug(
                f"knowledge_search_expanded client_id={client_id} request_id={request_id_str} "
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
        query_hash = sha256(query.encode()).hexdigest()[:12]
        skipped_aliases: list[str] = []
        request_id_str = request_id or "na"

        async def _search_targets(targets: list[str]) -> list[str]:
            params: dict[str, Any] = {
                "datasets": targets,
                "user": cls._to_user_or_none(user),
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
                    logger.info(f"knowledge_dataset_cognify_start dataset={alias} request_id={request_id_str}")
                ready = await cls._ensure_dataset_projected(dataset, user, timeout=2.0)
            except Exception as warm_exc:  # noqa: BLE001
                logger.debug(
                    f"knowledge_dataset_projection_warm_failed dataset={alias} request_id={request_id_str} "
                    f"detail={warm_exc}"
                )
                skipped_aliases.append(alias)
                continue
            if ready:
                ready_datasets.append(dataset)
                if user is not None:
                    logger.info(f"knowledge_dataset_cognify_ok dataset={alias} request_id={request_id_str}")
                continue
            if user is not None:
                logger.warning(
                    f"knowledge_dataset_search_skipped dataset={alias} request_id={request_id_str} "
                    "reason=projection_pending"
                )
            skipped_aliases.append(alias)

        if not ready_datasets:
            if skipped_aliases:
                cls._log_once(
                    f"search:{request_id_str}:{','.join(skipped_aliases)}",
                    logging.DEBUG,
                    f"knowledge_search_skipped client_id={client_id} request_id={request_id_str} "
                    f"datasets={','.join(skipped_aliases)}",
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
                f"knowledge_search_ok client_id={client_id} request_id={request_id_str} "
                f"query_hash={query_hash} results={len(results)}"
            )
            if not results:
                await asyncio.sleep(0.25)
                retry = await _search_targets(ready_datasets)
                if retry:
                    logger.warning(
                        f"knowledge_search_retry_after_empty client_id={client_id} request_id={request_id_str} "
                        f"query_hash={query_hash} results={len(retry)}"
                    )
                    results = retry
            return await cls._build_snippets(results, ready_datasets, user)
        except (PermissionDeniedError, DatasetNotFoundError) as exc:
            logger.warning(
                f"knowledge_search_issue client_id={client_id} request_id={request_id_str} "
                f"query_hash={query_hash} detail={exc}"
            )
            return []
        except Exception as exc:
            ready_aliases = [cls._alias_for_dataset(ds) for ds in ready_datasets]
            if cls._is_graph_missing_error(exc):
                for alias in ready_aliases:
                    cls._PROJECTED_DATASETS.discard(alias)
                logger.warning(
                    f"knowledge_dataset_search_skipped dataset={','.join(ready_aliases)} request_id={request_id_str} "
                    f"reason=projection_incomplete detail={exc}"
                )
                return []
            logger.warning(
                f"knowledge_search_failed client_id={client_id} request_id={request_id_str} "
                f"query_hash={query_hash} detail={exc}"
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

        digest_pairs = [cls._compute_digests(normalized_text) for _, normalized_text, _, _ in prepared]
        digests_sha = [pair[0] for pair in digest_pairs]
        dataset_list = list(datasets)
        metadata_results: list[tuple[str | None, Mapping[str, Any] | None]] = [(None, None)] * len(prepared)
        pending: list[int] = []

        for index, ((_, _, dataset_hint, metadata), _) in enumerate(zip(prepared, digest_pairs, strict=False)):
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
        for (text, normalized_text, dataset_hint, _), (digest_sha, digest_md5), (resolved_dataset, payload) in zip(
            prepared, digest_pairs, metadata_results, strict=False
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
                digest_md5=digest_md5,
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

    @classmethod
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
    def _storage_path_for_digest(cls, digest_md5: str) -> Path:
        return cls._storage_root() / f"text_{digest_md5}.txt"

    @classmethod
    def _read_storage_text(cls, digest_md5: str) -> str | None:
        if not digest_md5:
            return None
        path = cls._storage_path_for_digest(digest_md5)
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            cls._log_once(
                f"storage_read:{digest_md5[:12]}",
                logging.DEBUG,
                f"knowledge_storage_read_failed digest_md5={digest_md5[:12]} detail={exc}",
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
    def _metadata_digest_md5(cls, metadata: Mapping[str, Any] | None) -> str | None:
        if not metadata:
            return None
        for key in ("digest_md5", "md5", "checksum_md5"):
            value = metadata.get(key)
            if isinstance(value, str):
                candidate = value.strip()
                if candidate:
                    return candidate
        return None

    @classmethod
    def _prepare_dataset_row(cls, raw: Any, alias: str) -> DatasetRow:
        text_value = getattr(raw, "text", None)
        base_text = str(text_value or "")
        metadata_obj = getattr(raw, "metadata", None)
        metadata_map = cls._coerce_metadata(metadata_obj)
        digest_md5 = cls._metadata_digest_md5(metadata_map)
        if not digest_md5:
            digest_md5 = cls._digest_from_raw_location(getattr(raw, "raw_data_location", None))
        normalized_text = cls._normalize_text(base_text)
        if not normalized_text and digest_md5:
            storage_text = cls._read_storage_text(digest_md5)
            if storage_text is not None:
                normalized_text = cls._normalize_text(storage_text)
        metadata_dict: dict[str, Any] | None = dict(metadata_map) if metadata_map else None
        if metadata_dict is not None:
            metadata_dict.setdefault("dataset", alias)
        text_output = normalized_text if normalized_text else base_text
        if normalized_text:
            digest_sha, digest_md5_calc = cls._compute_digests(normalized_text)
            if metadata_dict is None:
                metadata_dict = {"dataset": alias}
            metadata_dict.setdefault("digest_sha", digest_sha)
            metadata_dict["digest_md5"] = digest_md5_calc
            digest_md5 = metadata_dict["digest_md5"]
        else:
            if metadata_dict is None and digest_md5:
                metadata_dict = {"dataset": alias, "digest_md5": digest_md5}
            elif metadata_dict is not None and digest_md5:
                metadata_dict.setdefault("digest_md5", digest_md5)
        if metadata_dict and not metadata_dict.get("dataset"):
            metadata_dict["dataset"] = alias
        if metadata_dict is not None and not metadata_dict:
            metadata_dict = None
        return DatasetRow(text=text_output, metadata=metadata_dict)

    @classmethod
    def _normalize_text(cls, text: str | None) -> str:
        return normalize_text(text)

    @classmethod
    def _augment_metadata(
        cls,
        metadata: Mapping[str, Any] | None,
        dataset_alias: str | None,
        *,
        digest_sha: str,
        digest_md5: str,
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
        payload["digest_md5"] = digest_md5
        if "kind" not in payload:
            payload["kind"] = "document"
        return payload

    @staticmethod
    def _compute_digests(normalized_text: str) -> tuple[str, str]:
        payload = normalized_text.encode("utf-8")
        digest_sha = sha256(payload).hexdigest()
        digest_md5 = md5(payload).hexdigest()
        return digest_sha, digest_md5

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
            digest_md5_meta = cls._metadata_digest_md5(entry.metadata)
            if not normalized and digest_md5_meta:
                storage_text = cls._read_storage_text(digest_md5_meta)
                if storage_text is not None:
                    normalized = cls._normalize_text(storage_text)
            if not normalized:
                continue
            digest_sha, digest_md5 = cls._compute_digests(normalized)
            storage_root = cls._storage_root()
            storage_path = storage_root / f"text_{digest_md5}.txt"
            if not storage_path.exists():
                missing += 1
                stored_md5 = await HashStore.get_md5_for_sha(alias, digest_sha)
                if stored_md5 and stored_md5 != digest_md5:
                    logger.debug(
                        f"knowledge_dataset_digest_mismatch dataset={alias} digest_sha={digest_sha[:12]} "
                        f"stored_md5={stored_md5[:12]} expected_md5={digest_md5[:12]}"
                    )
            _, created = cls._ensure_storage_file(digest_md5, normalized, dataset=alias)
            if created:
                healed += 1
            metadata_payload = cls._augment_metadata(
                entry.metadata, alias, digest_sha=digest_sha, digest_md5=digest_md5
            )
            add_tasks.append(HashStore.add(alias, digest_sha, metadata=metadata_payload))
        if add_tasks:
            await asyncio.gather(*add_tasks)
        if missing or healed:
            logger.debug(
                f"knowledge_dataset_storage_heal dataset={alias} reason={reason} missing={missing} healed={healed}"
            )
            cls._log_storage_state(alias, missing_count=missing, healed_count=healed)
        return missing, healed

    @classmethod
    def _ensure_storage_file(cls, digest_md5: str, text: str, *, dataset: str | None = None) -> tuple[Path, bool]:
        root = cls._storage_root()
        path = root / f"text_{digest_md5}.txt"
        if path.exists():
            return path, False
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.replace(path)
            return path, True
        except Exception as exc:  # noqa: BLE001 - log and proceed with Cognee handling
            logger.warning(
                f"knowledge_storage_write_failed digest={digest_md5[:12]} dataset={dataset or 'unknown'} "
                f"path={path} detail={exc}"
            )
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001 - best effort cleanup
                pass
            return path, False

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
        target_alias = cls._resolve_dataset_alias(ds)
        meta_payload.setdefault("dataset", target_alias)
        attempts = 0
        role_label = role.value if role else "document"
        while attempts < 2:
            try:
                logger.debug(f"kb_append start dataset={target_alias} role={role_label} length={len(text)}")
                resolved_name, created = await cls.update_dataset(
                    text,
                    target_alias,
                    user,
                    node_set=list(node_set or []),
                    metadata=meta_payload,
                )
                if created:
                    task = asyncio.create_task(cls._process_dataset(resolved_name, user))
                    task.add_done_callback(cls._log_task_exception)
                return
            except PermissionDeniedError:
                raise
            except FileNotFoundError as exc:
                logger.warning(f"kb_append storage_missing dataset={target_alias} detail={exc}")
                await HashStore.clear(target_alias)
                cls._PROJECTED_DATASETS.discard(cls._alias_for_dataset(target_alias))
                rebuilt = await cls.rebuild_dataset(target_alias, user)
                if not rebuilt:
                    logger.warning(f"kb_append rebuild_failed dataset={target_alias}")
                    break
                attempts += 1
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"kb_append skipped dataset={target_alias}: {exc}", exc_info=True)
                break
        logger.warning(f"kb_append aborted dataset={target_alias}")

    @classmethod
    async def save_client_message(cls, text: str, client_id: int) -> None:
        await cls.add_text(
            text,
            client_id=client_id,
            role=MessageRole.CLIENT,
            node_set=[f"client:{client_id}", "chat_message"],
        )
        user = await cls._get_cognee_user()
        dataset = cls._resolve_dataset_alias(cls._dataset_name(client_id))
        user_ns = cls._to_user_or_none(user)
        if await cls._wait_for_projection(dataset, user_ns, user=user, timeout=1.5):
            cls._PROJECTED_DATASETS.add(cls._alias_for_dataset(dataset))

    @classmethod
    async def save_ai_message(cls, text: str, client_id: int) -> None:
        await cls.add_text(
            text,
            client_id=client_id,
            role=MessageRole.AI_COACH,
            node_set=[f"client:{client_id}", "chat_message"],
        )
        user = await cls._get_cognee_user()
        dataset = cls._resolve_dataset_alias(cls._dataset_name(client_id))
        user_ns = cls._to_user_or_none(user)
        if await cls._wait_for_projection(dataset, user_ns, user=user, timeout=1.5):
            cls._PROJECTED_DATASETS.add(cls._alias_for_dataset(dataset))

    @classmethod
    async def get_message_history(cls, client_id: int, limit: int | None = None) -> list[str]:
        """Return recent chat messages for a client."""
        dataset: str = cls._resolve_dataset_alias(cls._dataset_name(client_id))
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
        user_ns: Any | None = cls._to_user_or_none(user)
        try:
            data = await cls._fetch_dataset_rows(list_data_callable, dataset, user, user_ns)
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
    def _log_once(cls, key: str | tuple[str, ...], level: int, message: str, *, min_interval: float = 30.0) -> None:
        now = time.time()
        if isinstance(key, tuple):
            storage_key = "|".join(key)
        else:
            storage_key = key
        last = cls._LOG_THROTTLE.get(storage_key, 0.0)
        if now - last >= min_interval:
            log_method = getattr(logger, "log", None)
            if callable(log_method):
                log_method(level, message)
            else:
                logging.getLogger(__name__).log(level, message)
            cls._LOG_THROTTLE[storage_key] = now

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
    async def _get_dataset_id(cls, dataset: str, user: Any | None, user_ns: Any | None) -> str | None:
        alias = cls._alias_for_dataset(dataset)
        if cls._looks_like_uuid(dataset):
            cls._register_dataset_identifier(alias, dataset)
            cls._log_once(
                f"dataset_resolved:{alias}",
                logging.DEBUG,
                f"kb_dataset_resolved name={alias} id={dataset}",
                min_interval=5.0,
            )
            return dataset
        identifier = cls._DATASET_IDS.get(alias)
        if identifier:
            cls._log_once(
                f"dataset_resolved:{alias}",
                logging.DEBUG,
                f"kb_dataset_resolved name={alias} id={identifier}",
                min_interval=5.0,
            )
            return identifier
        if user is not None:
            try:
                await cls._ensure_dataset_exists(alias, user)
            except Exception as exc:  # noqa: BLE001 - diagnostics only
                logger.debug(f"knowledge_dataset_id_lookup_failed dataset={alias} detail={exc}")
            else:
                identifier = cls._DATASET_IDS.get(alias)
                if identifier:
                    cls._log_once(
                        f"dataset_resolved:{alias}",
                        logging.DEBUG,
                        f"kb_dataset_resolved name={alias} id={identifier}",
                        min_interval=5.0,
                    )
                    return identifier
        if user is not None:
            metadata = await cls._get_dataset_metadata(alias, user)
            if metadata is not None:
                identifier = cls._extract_dataset_identifier(metadata)
                if identifier:
                    cls._register_dataset_identifier(alias, identifier)
                    cls._log_once(
                        f"dataset_resolved:{alias}",
                        logging.DEBUG,
                        f"kb_dataset_resolved name={alias} id={identifier}",
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
        user_ns = cls._to_user_or_none(user)
        if user_ns is None:
            logger.debug(f"Dataset ensure skipped dataset={name}: user context unavailable")
            return
        canonical = cls._resolve_dataset_alias(name)
        try:
            from cognee.modules.data.methods import (  # type: ignore
                get_authorized_dataset_by_name,
                create_authorized_dataset,
            )
        except Exception:
            return
        exists = await get_authorized_dataset_by_name(canonical, user_ns, "write")  # pyrefly: ignore[bad-argument-type]
        if exists is not None:
            identifier = cls._extract_dataset_identifier(exists)
            if identifier:
                cls._register_dataset_identifier(canonical, identifier)
            return
        created = await create_authorized_dataset(canonical, user_ns)  # pyrefly: ignore[bad-argument-type]
        identifier = cls._extract_dataset_identifier(created)
        if identifier:
            cls._register_dataset_identifier(canonical, identifier)

    @classmethod
    async def _ensure_dataset_projected(
        cls,
        dataset: str,
        user: Any | None,
        *,
        timeout: float = 2.0,
    ) -> bool:
        alias = cls._alias_for_dataset(dataset)
        user_ns = cls._to_user_or_none(user)
        if await cls._wait_for_projection(dataset, user_ns, user=user, timeout=timeout):
            cls._PROJECTED_DATASETS.add(alias)
            return True
        if user is None:
            return False
        try:
            logger.debug(f"knowledge_dataset_cognify_start dataset={alias}")
            await cls._process_dataset(dataset, user)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"knowledge_dataset_projection_warm_failed dataset={alias} detail={exc}")
            return False
        else:
            logger.debug(f"knowledge_dataset_cognify_ok dataset={alias}")
        if await cls._wait_for_projection(dataset, user_ns, user=user, timeout=timeout):
            cls._PROJECTED_DATASETS.add(alias)
            return True
        return False

    @classmethod
    def _dataset_name(cls, client_id: int) -> str:
        """Generate canonical dataset alias for a client profile."""
        return f"{cls._CLIENT_ALIAS_PREFIX}{client_id}"

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
        user_ns: Any | None,
    ) -> list[Any]:
        """Fetch dataset rows, gracefully handling legacy signatures."""
        alias = cls._alias_for_dataset(dataset)
        dataset_id = await cls._get_dataset_id(dataset, user, user_ns)
        if dataset_id is None:
            cls._log_once(
                f"projection:{alias}:dataset_id_unavailable",
                logging.WARNING,
                f"knowledge_projection_pending dataset={alias} reason=dataset_id_unavailable",
            )
            raise ProjectionProbeError(f"dataset_id_unavailable alias={alias}")

        if user_ns is not None:
            if cls._list_data_supports_user is None or cls._list_data_requires_user is None:
                supports, requires = cls._describe_list_data(list_data)
                if supports is not None:
                    cls._list_data_supports_user = supports
                if requires is not None:
                    cls._list_data_requires_user = requires

        if user_ns is not None and cls._list_data_supports_user is not False:
            try:
                rows = await list_data(dataset_id, user=user_ns)
            except TypeError:
                logger.debug("cognee.datasets.list_data rejected keyword 'user', retrying without keyword")
                cls._list_data_supports_user = False
                if cls._list_data_requires_user:
                    logger.debug("cognee.datasets.list_data requires user context, retrying positional call")
                    rows = await list_data(dataset_id, user_ns)
                    cls._list_data_supports_user = True
                    return list(rows)
            else:
                cls._list_data_supports_user = True
                return list(rows)

        if user_ns is not None and cls._list_data_requires_user:
            rows = await list_data(dataset_id, user_ns)
            cls._list_data_supports_user = True
            return list(rows)

        try:
            rows = await list_data(dataset_id)
        except TypeError as exc:
            if user_ns is not None:
                logger.debug(
                    f"cognee.datasets.list_data raised {exc.__class__.__name__}: retrying with positional user"
                )
                rows = await list_data(dataset_id, user_ns)
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
            user_ns = cls._to_user_or_none(user)
            try:
                dataset_id = await cls._get_dataset_id(alias, user, user_ns)
            except ProjectionProbeError:
                dataset_id = None
            cls._log_once(
                f"projection:{alias}:process",
                logging.DEBUG,
                f"kb_pipeline_start dataset={alias} dataset_id={dataset_id}",
                min_interval=5.0,
            )
            await cls._project_dataset(alias, user)
            cls._PROJECTED_DATASETS.add(alias)

    @staticmethod
    def _log_task_exception(task: asyncio.Task[Any]) -> None:
        """Log exception from a background task."""
        if exc := task.exception():
            logger.warning(f"Dataset processing failed: {exc}", exc_info=True)

    @classmethod
    def _to_user_or_none(cls, user: Any) -> Any | None:
        """Normalize user object into SimpleNamespace or return None."""
        if user is None:
            return None
        if isinstance(user, CogneeUser):
            return SimpleNamespace(**asdict(user))
        if is_dataclass(user):
            d = asdict(user)
            return SimpleNamespace(**d) if d.get("id") else None
        if getattr(user, "id", None):
            return user
        return None

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
        user_ns = cls._to_user_or_none(user)
        dataset_id = await cls._get_dataset_id(alias, user, user_ns)
        target = dataset_id or alias
        cls._log_once(
            f"projection:{alias}:cognify_start",
            logging.DEBUG,
            f"knowledge_dataset_cognify_start dataset={alias} dataset_id={dataset_id}",
            min_interval=5.0,
        )
        try:
            await cognee.cognify(datasets=[target], user=user_ns)  # pyrefly: ignore[bad-argument-type]
        except FileNotFoundError as exc:
            missing_path = getattr(exc, "filename", None) or str(exc)
            logger.warning(f"knowledge_dataset_storage_missing dataset={alias} missing={missing_path}")
            missing, healed = await cls._heal_dataset_storage(alias, user, reason="cognify_missing")
            if missing == 0 and healed == 0:
                cls._log_storage_state(alias, missing_count=0, healed_count=0)
            cls._PROJECTED_DATASETS.discard(alias)
            if healed > 0:
                await cls._project_dataset(alias, user, allow_rebuild=allow_rebuild)
                return
            if allow_rebuild and await cls.rebuild_dataset(alias, user):
                logger.info(f"knowledge_dataset_rebuilt dataset={alias}")
                await cls._project_dataset(alias, user, allow_rebuild=False)
                return
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"knowledge_dataset_cognify_failed dataset={dataset} detail={exc}")
            raise
        cls._log_once(
            f"projection:{alias}:cognify_done",
            logging.DEBUG,
            f"kb_pipeline_done dataset={alias} dataset_id={dataset_id}",
            min_interval=5.0,
        )
        projected = await cls._wait_for_projection(alias, user_ns, user=user)
        if not projected:
            logger.debug(f"knowledge_dataset_projection_pending dataset={alias} result=timeout")

    @classmethod
    async def rebuild_dataset(cls, dataset: str, user: Any | None) -> bool:
        """Rebuild dataset content by re-adding raw entries and clearing hash store."""
        alias = cls._alias_for_dataset(dataset)
        try:
            await cls._ensure_dataset_exists(alias, user)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"knowledge_dataset_rebuild_ensure_failed dataset={alias} detail={exc}")
        await cls._heal_dataset_storage(alias, user, reason="rebuild_preflight")
        try:
            entries = await cls._list_dataset_entries(alias, user)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"knowledge_dataset_rebuild_list_failed dataset={alias} detail={exc}")
            return False
        if not entries:
            _, healed = await cls._heal_dataset_storage(alias, user, reason="rebuild_retry")
            if healed > 0:
                try:
                    entries = await cls._list_dataset_entries(alias, user)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"knowledge_dataset_rebuild_list_retry_failed dataset={alias} detail={exc}")
                    return False
            if not entries:
                hashes = await HashStore.list(alias)
                logger.debug(
                    f"knowledge_dataset_rebuild_skipped dataset={alias}: no_entries hashstore_size={len(hashes)}"
                )
                logger.warning(f"knowledge_dataset_rebuild_skipped dataset={alias}: no_entries")
                return False
        await HashStore.clear(alias)
        cls._PROJECTED_DATASETS.discard(alias)
        reinserted = 0
        last_dataset: str | None = None
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
            return False
        logger.info(f"knowledge_dataset_rebuild_ready dataset={alias} documents={reinserted}")
        if last_dataset:
            await cls._process_dataset(last_dataset, user)
        return True

    @classmethod
    async def _wait_for_projection(
        cls,
        dataset: str,
        user_ns: Any | None,
        *,
        user: Any | None = None,
        timeout: float | None = None,
    ) -> bool:
        alias = cls._alias_for_dataset(dataset)
        start = monotonic()
        deadline = start + timeout if timeout is not None and timeout > 0 else None
        backoff = cls._PROJECTION_BACKOFF_SECONDS or (0.5,)
        delay_index = 0
        delay = backoff[delay_index]
        fatal_error = False

        async def _ready() -> bool:
            nonlocal fatal_error
            try:
                return await cls._is_projection_ready(dataset, user_ns, user=user)
            except ProjectionProbeError:
                fatal_error = True
                return False
            except Exception as probe_exc:  # noqa: BLE001
                cls._log_once(
                    f"projection:{alias}:probe_exception",
                    logging.DEBUG,
                    f"knowledge_projection_probe_error dataset={alias} detail={probe_exc}",
                )
                return False

        if await _ready():
            cls._log_once(
                f"projection:{alias}:ready",
                logging.DEBUG,
                f"knowledge_projection_wait dataset={alias} elapsed_ms={0} result=ready",
                min_interval=5.0,
            )
            return True
        if fatal_error:
            return False

        while True:
            jitter = random.uniform(0.0, min(1.0, delay * 0.1))
            sleep_for = delay + jitter
            next_time = monotonic() + sleep_for
            if deadline is not None and next_time > deadline:
                break
            await asyncio.sleep(sleep_for)
            if await _ready():
                elapsed_ms = int((monotonic() - start) * 1000)
                cls._log_once(
                    f"projection:{alias}:ready",
                    logging.DEBUG,
                    f"knowledge_projection_wait dataset={alias} elapsed_ms={elapsed_ms} result=ready",
                    min_interval=5.0,
                )
                return True
            if fatal_error:
                return False
            if delay_index < len(backoff) - 1:
                delay_index += 1
                delay = backoff[delay_index]

        # One last probe without waiting if deadline was reached
        if await _ready():
            elapsed_ms = int((monotonic() - start) * 1000)
            cls._log_once(
                f"projection:{alias}:ready_after_timeout",
                logging.DEBUG,
                f"knowledge_projection_wait dataset={alias} elapsed_ms={elapsed_ms} result=ready_after_timeout",
                min_interval=5.0,
            )
            return True

        elapsed_ms = int((monotonic() - start) * 1000)
        cls._log_once(
            f"projection:{alias}:timeout",
            logging.WARNING,
            f"knowledge_projection_wait dataset={alias} elapsed_ms={elapsed_ms} result=timeout",
        )
        return False

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
    async def _is_projection_ready(cls, dataset: str, user_ns: Any | None, *, user: Any | None = None) -> bool:
        """Return True if the dataset projection looks ready for querying."""
        alias = cls._alias_for_dataset(dataset)
        state = cls._projection_state(alias)
        now = time.time()
        if now < state["next_check_ts"]:
            return state["status"] == "ready"

        datasets_module = getattr(cognee, "datasets", None)
        if datasets_module is None:
            cls._log_once(
                (alias, "projection_pending", "datasets_module_missing"),
                logging.DEBUG,
                f"knowledge_projection_pending dataset={alias} reason=datasets_module_missing",
                min_interval=15.0,
            )
            state["status"] = "pending"
            state["reason"] = "datasets_module_missing"
            state["next_check_ts"] = now + random.uniform(20.0, 40.0)
            return False
        list_data = getattr(datasets_module, "list_data", None)
        if not callable(list_data):
            cls._log_once(
                (alias, "projection_pending", "list_data_missing"),
                logging.DEBUG,
                f"knowledge_projection_pending dataset={alias} reason=list_data_missing",
                min_interval=15.0,
            )
            state["status"] = "pending"
            state["reason"] = "list_data_missing"
            state["next_check_ts"] = now + random.uniform(20.0, 40.0)
            return False

        list_data_callable = cast(Callable[..., Awaitable[Iterable[Any]]], list_data)
        try:
            rows = await cls._fetch_dataset_rows(list_data_callable, dataset, user, user_ns)
        except ProjectionProbeError as probe_exc:
            state["status"] = "pending"
            state["reason"] = "dataset_id_unavailable"
            state["next_check_ts"] = now + random.uniform(20.0, 40.0)
            cls._log_once(
                (alias, "projection_pending", "dataset_id_unavailable"),
                logging.WARNING,
                f"knowledge_projection_pending dataset={alias} reason=dataset_id_unavailable detail={probe_exc}",
                min_interval=30.0,
            )
            return False
        except Exception as exc:  # noqa: BLE001
            state["status"] = "pending"
            state["reason"] = "list_data_error"
            state["next_check_ts"] = now + random.uniform(45.0, 90.0)
            cls._log_once(
                (alias, "projection_pending", "list_data_error"),
                logging.WARNING,
                f"knowledge_projection_pending dataset={alias} reason=list_data_error detail={exc}",
                min_interval=30.0,
            )
            return False

        rows = list(rows)
        row_count = len(rows)
        cls._log_once(
            f"projection:{alias}:row_count",
            logging.DEBUG,
            f"kb_projection_rows dataset={alias} rows={row_count}",
            min_interval=30.0,
        )
        doc_rows = 0
        message_rows = 0
        content_rows = 0
        missing_files = 0
        entries_snapshot: list[DatasetRow] = []
        for raw_row in rows:
            prepared = cls._prepare_dataset_row(raw_row, alias)
            entries_snapshot.append(prepared)
            digest_md5 = cls._metadata_digest_md5(prepared.metadata)
            normalized_entry = cls._normalize_text(prepared.text)
            if not normalized_entry:
                if digest_md5 and not cls._storage_path_for_digest(digest_md5).exists():
                    missing_files += 1
                continue
            content_rows += 1
            if digest_md5 and not cls._storage_path_for_digest(digest_md5).exists():
                missing_files += 1
            kind_value = cls._resolve_snippet_kind(prepared.metadata, normalized_entry)
            if kind_value == "message":
                message_rows += 1
                continue
            doc_rows += 1
        if missing_files > 0:
            missing, healed = await cls._heal_dataset_storage(
                dataset,
                user,
                entries=entries_snapshot,
                reason="projection_missing_storage",
            )
            if healed > 0:
                state["status"] = "pending"
                state["reason"] = "healing"
                state["next_check_ts"] = now + random.uniform(4.0, 8.0)
                cls._log_once(
                    (alias, "projection_pending", "healing_missing"),
                    logging.DEBUG,
                    (
                        f"knowledge_projection_pending dataset={alias} reason=healing_missing "
                        f"missing={missing} healed={healed}"
                    ),
                    min_interval=15.0,
                )
                return False
        if doc_rows > 0:
            cls._log_once(
                f"projection:{alias}:documents",
                logging.DEBUG,
                f"kb_projection_documents dataset={alias} documents={doc_rows}",
                min_interval=30.0,
            )
        if content_rows == 0:
            missing = healed = 0
            if row_count > 0:
                missing, healed = await cls._heal_dataset_storage(
                    dataset,
                    user,
                    entries=entries_snapshot,
                    reason="projection_no_documents",
                )
                if healed > 0:
                    state["status"] = "pending"
                    state["reason"] = "healing"
                    state["next_check_ts"] = now + random.uniform(4.0, 8.0)
                    cls._log_once(
                        (alias, "projection_pending", "healing"),
                        logging.DEBUG,
                        (
                            f"knowledge_projection_pending dataset={alias} reason=healing "
                            f"missing={missing} healed={healed}"
                        ),
                        min_interval=15.0,
                    )
                    return False
            state["status"] = "pending"
            state["reason"] = "no_documents"
            state["next_check_ts"] = now + random.uniform(30.0, 45.0)
            cls._log_once(
                (alias, "projection_pending", "no_documents"),
                logging.DEBUG,
                f"knowledge_projection_pending dataset={alias} reason=no_documents rows={row_count}",
                min_interval=30.0,
            )
            return False
        if doc_rows == 0 and message_rows > 0:
            cls._log_once(
                (alias, "projection_messages_only"),
                logging.DEBUG,
                f"kb_projection_messages dataset={alias} messages={message_rows}",
                min_interval=30.0,
            )

        graph_logger = logging.getLogger("GraphCompletionRetriever")
        previous_level = graph_logger.level
        graph_logger.setLevel(logging.ERROR)
        try:
            await cognee.search(
                cls._PROJECTION_CHECK_QUERY,
                datasets=[dataset],
                user=user_ns,
                top_k=1,
            )
        except Exception as exc:  # noqa: BLE001
            if cls._is_graph_missing_error(exc):
                state["status"] = "pending"
                state["reason"] = "projection_incomplete"
                state["next_check_ts"] = now + random.uniform(10.0, 20.0)
                cls._log_once(
                    (alias, "projection_pending", "projection_incomplete"),
                    logging.DEBUG,
                    f"knowledge_projection_pending dataset={alias} reason=projection_incomplete",
                    min_interval=15.0,
                )
                return False
            state["status"] = "pending"
            state["reason"] = "probe_error"
            state["next_check_ts"] = now + random.uniform(20.0, 40.0)
            cls._log_once(
                (alias, "projection_pending", "probe_error"),
                logging.DEBUG,
                f"knowledge_projection_probe_error dataset={alias} detail={exc}",
                min_interval=15.0,
            )
            return False
        finally:
            graph_logger.setLevel(previous_level)

        state["status"] = "ready"
        state["reason"] = None
        state["next_check_ts"] = now + 5.0
        return True

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
                dig_sha, dig_md5 = cls._compute_digests(normalized)
                ensured_metadata = cls._augment_metadata(metadata_dict, alias, digest_sha=dig_sha, digest_md5=dig_md5)
                cls._ensure_storage_file(dig_md5, normalized, dataset=alias)
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
            logger.debug(f"knowledge_dataset_list_ensure_failed dataset={alias} detail={exc}")
        user_ns = cls._to_user_or_none(user)
        try:
            rows = await cls._fetch_dataset_rows(
                cast(Callable[..., Awaitable[Iterable[Any]]], list_data),
                alias,
                user,
                user_ns,
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
        user_ns = cls._to_user_or_none(user)
        info: dict[str, Any] = {
            "alias": alias,
            "resolved": resolved,
            "id": resolved,
            "documents": None,
            "projected": None,
            "last_error": None,
        }
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
        try:
            info["projected"] = await cls._is_projection_ready(resolved, user_ns, user=user)
        except Exception as exc:  # noqa: BLE001
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
        try:
            return await get_authorized_dataset_by_name(
                dataset, cls._to_user_or_none(user), "read"
            )  # pyrefly: ignore[bad-argument-type]
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"knowledge_dataset_metadata_failed dataset={dataset} detail={exc}")
            return None
