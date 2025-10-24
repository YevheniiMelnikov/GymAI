import asyncio
import inspect
from dataclasses import asdict, dataclass, is_dataclass
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, ClassVar, Iterable, Mapping, Sequence, cast
from uuid import UUID

from loguru import logger

from ai_coach.agent.knowledge.base_knowledge_loader import KnowledgeLoader
from ai_coach.agent.knowledge.cognee_config import CogneeConfig
from ai_coach.agent.knowledge.utils.hash_store import HashStore
from ai_coach.agent.knowledge.utils.lock_cache import LockCache
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
    _PROJECTION_BACKOFF_SECONDS: tuple[float, ...] = (0.5, 1.0, 2.0, 4.0)

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

    @classmethod
    async def refresh(cls) -> None:
        """Re-cognify global dataset and refresh loader if available."""
        user = await cls._get_cognee_user()
        ds = cls._resolve_dataset_alias(cls.GLOBAL_DATASET)
        await cls._ensure_dataset_exists(ds, user)
        cls._PROJECTED_DATASETS.discard(cls._alias_for_dataset(ds))
        if cls._loader:
            await cls._loader.refresh()
        try:
            await cognee.cognify(datasets=[ds], user=cls._to_user_or_none(user))  # pyrefly: ignore[bad-argument-type]
        except (PermissionDeniedError, DatasetNotFoundError) as e:
            logger.error(f"Knowledge base update skipped: {e}")

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
        text = (text or "").strip()
        if not text:
            return dataset, False
        digest = sha256(text.encode()).hexdigest()
        ds_name = cls._resolve_dataset_alias(dataset)
        await cls._ensure_dataset_exists(ds_name, user)
        cls._ensure_storage_file(digest, text)
        if await HashStore.contains(ds_name, digest):
            return ds_name, False

        attempts = 0
        while attempts < 2:
            try:
                info = await _safe_add(
                    text,
                    dataset_name=ds_name,
                    user=cls._to_user_or_none(user),  # pyrefly: ignore[bad-argument-type]
                    node_set=node_set,
                )
            except FileNotFoundError:
                attempts += 1
                cls._ensure_storage_file(digest, text)
                if attempts >= 2:
                    raise
                logger.debug(
                    "knowledge_dataset_retry_missing_file dataset={} digest={} attempt={}",
                    ds_name,
                    digest[:12],
                    attempts,
                )
                continue
            except (DatasetNotFoundError, PermissionDeniedError):
                raise
            break
        await HashStore.add(ds_name, digest, metadata=metadata)
        resolved = ds_name
        identifier = cls._extract_dataset_identifier(info)
        if identifier:
            cls._register_dataset_identifier(ds_name, identifier)
            resolved = identifier
        return resolved, True

    @classmethod
    async def search(
        cls,
        query: str,
        client_id: int,
        k: int | None = None,
    ) -> list[KnowledgeSnippet]:
        """Search across client and global datasets with resiliency features."""
        normalized = query.strip()
        if not normalized:
            logger.debug(f"Knowledge search skipped client_id={client_id}: empty query")
            return []
        user = await cls._get_cognee_user()
        await cls._ensure_profile_indexed(client_id, user)
        datasets = [cls._dataset_name(client_id), cls.GLOBAL_DATASET]
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
        logger.debug(
            f"knowledge_search_start client_id={client_id} query_hash={base_hash}"
            f" datasets={datasets_hint} top_k={k if k is not None else 'default'}"
        )

        queries = cls._expanded_queries(normalized)
        if len(queries) > 1:
            logger.debug(
                f"knowledge_search_expanded client_id={client_id} variants={len(queries)} base_query_hash={base_hash}"
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
    ) -> list[KnowledgeSnippet]:
        query_hash = sha256(query.encode()).hexdigest()[:12]
        datasets_hint = ",".join(datasets)

        async def _search_targets(targets: list[str]) -> list[str]:
            params: dict[str, Any] = {
                "datasets": targets,
                "user": cls._to_user_or_none(user),
            }
            if k is not None:
                params["top_k"] = k
            return await cognee.search(query, **params)

        user_ns = cls._to_user_or_none(user)
        for dataset in datasets:
            alias = cls._alias_for_dataset(dataset)
            if alias in cls._PROJECTED_DATASETS:
                continue
            try:
                ready = await cls._is_projection_ready(dataset, user_ns)
            except Exception as probe_exc:  # noqa: BLE001
                logger.debug(f"knowledge_dataset_projection_probe_failed dataset={alias} detail={probe_exc}")
                ready = False
            if not ready:
                try:
                    await cls._process_dataset(dataset, user)
                except Exception as warm_exc:  # noqa: BLE001
                    logger.debug(f"knowledge_dataset_projection_warm_failed dataset={alias} detail={warm_exc}")
                else:
                    cls._PROJECTED_DATASETS.add(alias)
            else:
                await cls._wait_for_projection(dataset, user_ns)
                cls._PROJECTED_DATASETS.add(alias)

        try:
            results = await _search_targets(datasets)
            logger.debug(f"knowledge_search_ok client_id={client_id} query_hash={query_hash} results={len(results)}")
            return await cls._build_snippets(results, datasets, user)
        except (PermissionDeniedError, DatasetNotFoundError) as exc:
            logger.warning(f"Search issue client_id={client_id} query_hash={query_hash}: {exc}")
            return []
        except Exception as exc:
            message = str(exc)
            if cls._is_graph_missing_error(exc):
                logger.warning(
                    f"knowledge_search_graph_missing client_id={client_id} datasets={datasets_hint} detail={message}"
                )
                await cls._warm_up_datasets(datasets, user)
                try:
                    results = await _search_targets(datasets)
                    logger.debug(
                        "knowledge_search_ok client_id={} query_hash={} results={} retry=warm",
                        client_id,
                        query_hash,
                        len(results),
                    )
                    return await cls._build_snippets(results, datasets, user)
                except Exception as retry_exc:
                    if not cls._is_graph_missing_error(retry_exc):
                        logger.warning(
                            f"knowledge_search_retry_non_graph_error client_id={client_id} detail={retry_exc}"
                        )
                        return []
                    logger.warning(f"knowledge_search_retry_global_only client_id={client_id} detail={retry_exc}")
                    fallback_dataset = cls._resolve_dataset_alias(cls.GLOBAL_DATASET)
                    await cls._warm_up_datasets([fallback_dataset], user)
                    try:
                        results = await _search_targets([fallback_dataset])
                        logger.debug(
                            "knowledge_search_ok client_id={} query_hash={} results={} fallback=global",
                            client_id,
                            query_hash,
                            len(results),
                        )
                        return await cls._build_snippets(results, [fallback_dataset], user)
                    except Exception as final_exc:
                        if cls._is_graph_missing_error(final_exc):
                            fallback_entries = await cls._fallback_dataset_entries(
                                datasets,
                                user,
                                top_k=k,
                            )
                            if fallback_entries:
                                logger.info(
                                    "knowledge_search_dataset_fallback client_id={} results={}",
                                    client_id,
                                    len(fallback_entries),
                                )
                                snippets = await cls._build_snippets(fallback_entries, datasets, user)
                                return snippets
                            logger.warning(
                                f"knowledge_search_dataset_fallback_empty client_id={client_id} query_hash={query_hash}"
                            )
                        else:
                            logger.error(
                                "knowledge_search_retry_failed client_id={} query_hash={} detail={}",
                                client_id,
                                query_hash,
                                final_exc,
                            )
                        return []
            logger.error(f"Unexpected search error client_id={client_id}: {message}")
            return []

    @classmethod
    async def _build_snippets(
        cls,
        items: Iterable[Any],
        datasets: Sequence[str],
        user: Any | None,
    ) -> list[KnowledgeSnippet]:
        normalized: list[tuple[str, str | None, Mapping[str, Any] | None]] = []
        for raw in items:
            text, dataset_hint, metadata = cls._extract_search_item(raw)
            if not text:
                continue
            if metadata is not None and not isinstance(metadata, Mapping):
                metadata = cls._coerce_metadata(metadata)
            normalized.append((text, dataset_hint, metadata))
        if not normalized:
            return []

        digests = [sha256(text.encode()).hexdigest() for text, _, _ in normalized]
        dataset_list = list(datasets)
        metadata_results: list[tuple[str | None, Mapping[str, Any] | None]] = [(None, None)] * len(normalized)
        pending: list[int] = []

        for index, ((_, dataset_hint, metadata), _) in enumerate(zip(normalized, digests, strict=False)):
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
            lookups = await asyncio.gather(*(cls._collect_metadata(digests[i], datasets) for i in pending))
            for slot, (dataset_name, meta) in zip(pending, lookups, strict=False):
                alias_source = dataset_name or normalized[slot][1]
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
        for (text, dataset_hint, _), digest, (resolved_dataset, payload) in zip(
            normalized, digests, metadata_results, strict=False
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
            if dataset_alias:
                payload_dict.setdefault("dataset", dataset_alias)
                add_tasks.append(HashStore.add(dataset_alias, digest, metadata=payload_dict))
            else:
                payload_dict.pop("dataset", None)

            kind = cls._resolve_snippet_kind(payload_dict, text)
            if kind == "message":
                continue

            dataset_value = str(payload_dict.get("dataset") or dataset_alias or "").strip() or None
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
    def _ensure_storage_file(cls, digest: str, text: str) -> Path:
        root = cls._storage_root()
        path = root / f"text_{digest}.txt"
        if path.exists():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(text, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - log and proceed with Cognee handling
            logger.warning(
                "knowledge_storage_write_failed digest={} path={} detail={}",
                digest[:12],
                path,
                exc,
            )
        return path

    @classmethod
    async def add_text(
        cls,
        text: str,
        *,
        dataset: str | None = None,
        node_set: list[str] | None = None,
        client_id: int | None = None,
        role: MessageRole | None = None,
    ) -> None:
        """Add message text to a dataset, schedule cognify if new."""
        user = await cls._get_cognee_user()
        ds = dataset or (cls._dataset_name(client_id) if client_id is not None else cls.GLOBAL_DATASET)
        metadata: dict[str, Any] | None
        if role:
            text = f"{role.value}: {text}"
            metadata = {"kind": "message", "role": role.value}
        else:
            metadata = {"kind": "document"}
        target_alias = cls._resolve_dataset_alias(ds)
        meta_payload = dict(metadata) if metadata else None
        if meta_payload is not None:
            meta_payload.setdefault("dataset", target_alias)
        attempts = 0
        while attempts < 2:
            try:
                logger.debug(f"Updating dataset {target_alias}")
                resolved_name, created = await cls.update_dataset(
                    text,
                    target_alias,
                    user,
                    node_set=node_set or [],
                    metadata=meta_payload,
                )
                if created:
                    task = asyncio.create_task(cls._process_dataset(resolved_name, user))
                    task.add_done_callback(cls._log_task_exception)
                return
            except PermissionDeniedError:
                raise
            except FileNotFoundError as exc:
                logger.warning(f"Add text storage missing dataset={target_alias} detail={exc}")
                await HashStore.clear(target_alias)
                cls._PROJECTED_DATASETS.discard(cls._alias_for_dataset(target_alias))
                rebuilt = await cls.rebuild_dataset(target_alias, user)
                if not rebuilt:
                    logger.warning(f"Add text rebuild failed dataset={target_alias}")
                    break
                attempts += 1
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Add text skipped dataset={target_alias}: {exc}", exc_info=True)
                break
        logger.warning(f"Add text aborted dataset={target_alias}")

    @classmethod
    async def save_client_message(cls, text: str, client_id: int) -> None:
        await cls.add_text(text, client_id=client_id, role=MessageRole.CLIENT)

    @classmethod
    async def save_ai_message(cls, text: str, client_id: int) -> None:
        await cls.add_text(text, client_id=client_id, role=MessageRole.AI_COACH)

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
            data = await cls._fetch_dataset_rows(list_data_callable, dataset, user_ns)
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
        user_ns: Any | None,
    ) -> list[Any]:
        """Fetch dataset rows, gracefully handling legacy signatures."""
        if user_ns is not None:
            if cls._list_data_supports_user is None or cls._list_data_requires_user is None:
                supports, requires = cls._describe_list_data(list_data)
                if supports is not None:
                    cls._list_data_supports_user = supports
                if requires is not None:
                    cls._list_data_requires_user = requires

        if user_ns is not None and cls._list_data_supports_user is not False:
            try:
                rows = await list_data(dataset, user=user_ns)
            except TypeError:
                logger.debug("cognee.datasets.list_data rejected keyword 'user', retrying without keyword")
                cls._list_data_supports_user = False
                if cls._list_data_requires_user:
                    logger.debug("cognee.datasets.list_data requires user context, retrying positional call")
                    rows = await list_data(dataset, user_ns)
                    cls._list_data_supports_user = True
                    return list(rows)
            else:
                cls._list_data_supports_user = True
                return list(rows)

        if user_ns is not None and cls._list_data_requires_user:
            logger.debug("cognee.datasets.list_data requires user context, retrying positional call")
            rows = await list_data(dataset, user_ns)
            cls._list_data_supports_user = True
            return list(rows)

        try:
            rows = await list_data(dataset)
        except TypeError as exc:
            if user_ns is not None:
                logger.debug(
                    f"cognee.datasets.list_data raised {exc.__class__.__name__}: retrying with positional user"
                )
                rows = await list_data(dataset, user_ns)
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
            ds = cls._resolve_dataset_alias(dataset)
            await cls._project_dataset(ds, user)
            cls._PROJECTED_DATASETS.add(cls._alias_for_dataset(ds))

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
        user_ns = cls._to_user_or_none(user)
        alias = cls._alias_for_dataset(dataset)
        try:
            await cognee.cognify(datasets=[dataset], user=user_ns)  # pyrefly: ignore[bad-argument-type]
        except FileNotFoundError as exc:
            logger.warning(f"knowledge_dataset_storage_missing dataset={alias} detail={exc}")
            cls._log_storage_state(alias)
            await HashStore.clear(alias)
            cls._PROJECTED_DATASETS.discard(alias)
            if allow_rebuild and await cls.rebuild_dataset(alias, user):
                logger.info(f"knowledge_dataset_rebuilt dataset={alias}")
                await cls._project_dataset(dataset, user, allow_rebuild=False)
                return
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"knowledge_dataset_cognify_failed dataset={dataset} detail={exc}")
            raise

        await cls._wait_for_projection(dataset, user_ns)

    @classmethod
    async def rebuild_dataset(cls, dataset: str, user: Any | None) -> bool:
        """Rebuild dataset content by re-adding raw entries and clearing hash store."""
        alias = cls._alias_for_dataset(dataset)
        try:
            await cls._ensure_dataset_exists(alias, user)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"knowledge_dataset_rebuild_ensure_failed dataset={alias} detail={exc}")
        try:
            entries = await cls._list_dataset_entries(alias, user)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"knowledge_dataset_rebuild_list_failed dataset={alias} detail={exc}")
            return False
        if not entries:
            logger.warning(f"knowledge_dataset_rebuild_skipped dataset={alias}: no_entries")
            return False
        await HashStore.clear(alias)
        cls._PROJECTED_DATASETS.discard(alias)
        reinserted = 0
        last_dataset: str | None = None
        for entry in entries:
            normalized = entry.text.strip()
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
    async def _wait_for_projection(cls, dataset: str, user_ns: Any | None) -> None:
        if not cls._PROJECTION_BACKOFF_SECONDS:
            return
        for delay in cls._PROJECTION_BACKOFF_SECONDS:
            if await cls._is_projection_ready(dataset, user_ns):
                logger.debug(f"knowledge_dataset_projected dataset={dataset}")
                return
            await asyncio.sleep(delay)
        if await cls._is_projection_ready(dataset, user_ns):
            logger.debug(f"knowledge_dataset_projected dataset={dataset} after_timeout=True")
            return
        logger.warning(f"knowledge_dataset_projection_timeout dataset={dataset}")

    @classmethod
    def _log_storage_state(cls, dataset: str) -> None:
        storage_info = CogneeConfig.describe_storage()
        logger.warning(
            f"knowledge_dataset_storage_state dataset={dataset} storage_root={storage_info.get('root')} "
            f"root_exists={storage_info.get('root_exists')} root_writable={storage_info.get('root_writable')} "
            f"entries={storage_info.get('entries_count')} sample={storage_info.get('entries_sample')} "
            f"package_path={storage_info.get('package_path')} package_exists={storage_info.get('package_exists')} "
            f"package_is_symlink={storage_info.get('package_is_symlink')} "
            f"package_target={storage_info.get('package_target')}"
        )

    @classmethod
    async def _is_projection_ready(cls, dataset: str, user_ns: Any | None) -> bool:
        """Return True if the dataset projection looks ready for querying."""
        try:
            await cognee.search(
                cls._PROJECTION_CHECK_QUERY,
                datasets=[dataset],
                user=user_ns,
                top_k=1,
            )
        except Exception as exc:  # noqa: BLE001
            if cls._is_graph_missing_error(exc):
                return False
            logger.debug(f"knowledge_projection_probe_error dataset={dataset} detail={exc}")
            return True
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
                normalized = row.text.strip()
                if not normalized:
                    continue
                metadata = row.metadata
                if metadata is None:
                    metadata = cls._infer_metadata_from_text(normalized)
                metadata = dict(metadata) if metadata else {"kind": "document"}
                metadata.setdefault("dataset", alias)
                await HashStore.add(alias, sha256(normalized.encode()).hexdigest(), metadata=metadata)
                if metadata.get("kind") == "message":
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
        identifier = await cls._resolve_dataset_identifier(alias, user)
        try:
            rows = await cls._fetch_dataset_rows(
                cast(Callable[..., Awaitable[Iterable[Any]]], list_data),
                identifier,
                user_ns,
            )
        except Exception as exc:  # noqa: BLE001 - dataset listing is best effort
            logger.debug(f"knowledge_dataset_list_failed dataset={alias} detail={exc}")
            return []
        rows_data: list[DatasetRow] = []
        for row in rows:
            text = getattr(row, "text", None)
            if text:
                metadata = getattr(row, "metadata", None)
                if isinstance(metadata, Mapping):
                    meta_mapping: Mapping[str, Any] | None = dict(metadata)
                elif isinstance(metadata, dict):
                    meta_mapping = dict(metadata)
                else:
                    meta_mapping = None
                if meta_mapping is not None:
                    meta_dict = dict(meta_mapping)
                    meta_dict.setdefault("dataset", alias)
                else:
                    meta_dict = None
                rows_data.append(DatasetRow(text=str(text), metadata=meta_dict))
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
            info["projected"] = await cls._is_projection_ready(resolved, user_ns)
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
