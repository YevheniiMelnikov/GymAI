import hashlib
import inspect
import logging
from dataclasses import is_dataclass
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, ClassVar, Iterable, Mapping, Optional, cast
from uuid import NAMESPACE_DNS, UUID, uuid5

from loguru import logger

import cognee

from ai_coach.agent.knowledge.schemas import DatasetRow
from ai_coach.exceptions import ProjectionProbeError
from ai_coach.schemas import CogneeUser
from ai_coach.agent.knowledge.utils.helpers import _needs_cognee_setup
from config.app_settings import settings
from ai_coach.logging_config import log_once as global_log_once


class DatasetService:
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
    _BOOTSTRAP_USER_UUID: ClassVar[UUID] = uuid5(NAMESPACE_DNS, "gymbot_cognee_bootstrap_user")
    GLOBAL_DATASET: ClassVar[str] = settings.COGNEE_GLOBAL_DATASET

    def __init__(self):
        self._user: Any | None = None
        self._list_data_supports_user: bool | None = None
        self._list_data_requires_user: bool | None = None

    def alias_for_dataset(self, dataset: str) -> str:
        return self.resolve_dataset_alias(dataset)

    def resolve_dataset_alias(self, alias: str) -> str:
        stripped = (alias or "").strip()
        if not stripped:
            return alias
        mapped = self._DATASET_ALIASES.get(stripped)
        if mapped:
            return mapped
        return self._resolve_dataset_alias(stripped)

    def _dataset_from_metadata(self, meta: Mapping[str, Any] | None) -> str | None:
        if not meta:
            return None
        return cast(str | None, (meta.get("dataset") or meta.get("dataset_alias") or meta.get("datasetName")))

    def _extract_dataset_key(self, meta: Optional[Mapping[str, Any]]) -> Optional[str]:
        if not meta:
            return None
        raw_value = meta.get("dataset") or meta.get("dataset_alias") or meta.get("datasetName")
        if raw_value is None:
            raw_value = meta.get("datasetAlias") or meta.get("dataset_name")
        if raw_value is None:
            return None
        text = str(raw_value).strip()
        return text or None

    def alias_for(self, dataset: str) -> str:
        return self.alias_for_dataset(dataset)

    def dataset_from_metadata(self, metadata: Mapping[str, Any] | None) -> str | None:
        if metadata is None:
            return None
        candidate_keys = (
            "dataset",
            "dataset_name",
            "datasetName",
            "dataset_alias",
            "datasetAlias",
            "alias",
            "name",
        )
        for key in candidate_keys:
            value = metadata.get(key)
            if value in (None, ""):
                continue
            text = str(value).strip()
            if not text:
                continue
            try:
                return self.alias_for_dataset(text)
            except Exception:
                continue
        return None

    def register_dataset_identifier(self, alias: str, identifier: str) -> None:
        canonical = self._resolve_dataset_alias(alias)
        if not canonical:
            return
        self._DATASET_IDS[canonical] = identifier
        self._DATASET_ALIASES[identifier] = canonical

    def get_registered_identifier(self, dataset_or_alias: str) -> str | None:
        name = (dataset_or_alias or "").strip()
        if not name:
            return None
        # If a UUID-like is passed, treat it as identifier already
        if self._looks_like_uuid(name):
            return name
        canonical = self._resolve_dataset_alias(name)
        return self._DATASET_IDS.get(canonical)

    def dump_identifier_map(self) -> dict[str, str]:
        return dict(self._DATASET_IDS)

    async def get_dataset_id(self, dataset: str, user_ctx: Any | None) -> str | None:
        alias = self.alias_for_dataset(dataset)
        if self._looks_like_uuid(dataset):
            self.register_dataset_identifier(alias, dataset)
            if dataset:
                self.log_once(logging.DEBUG, "dataset_resolved", name=alias, id=dataset, min_interval=10.0)
            return dataset

        identifier = self._DATASET_IDS.get(alias)
        if identifier:
            self.log_once(logging.DEBUG, "dataset_resolved", name=alias, id=identifier, min_interval=10.0)
            return identifier

        if user_ctx is not None:
            try:
                await self.ensure_dataset_exists(alias, user_ctx)
                identifier = self._DATASET_IDS.get(alias)
                if identifier:
                    self.log_once(logging.DEBUG, "dataset_resolved", name=alias, id=identifier, min_interval=5.0)
                    return identifier
            except Exception as exc:
                logger.debug(f"knowledge_dataset_id_lookup_failed dataset={alias} detail={exc}")

        if user_ctx is not None:
            metadata = await self._get_dataset_metadata(alias, user_ctx)
            if metadata is not None:
                identifier = self._extract_dataset_identifier(metadata)
                if identifier:
                    self.register_dataset_identifier(alias, identifier)
                    self.log_once(
                        logging.DEBUG,
                        "dataset_resolved",
                        name=alias,
                        id=identifier,
                        min_interval=5.0,
                    )
                    return identifier
        return None

    def _extract_dataset_identifier(self, info: Any | None) -> str | None:
        if info is None:
            return None
        candidates: list[Any] = []
        if isinstance(info, dict):
            for key in self._DATASET_IDENTIFIER_FIELDS:
                if key in info:
                    candidates.append(info[key])
        for key in self._DATASET_IDENTIFIER_FIELDS:
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

    async def ensure_dataset_exists(self, name: str, user_ctx: Any | None) -> None:
        user_id = getattr(user_ctx, "id", None)
        if user_id is None:
            logger.debug(f"Dataset ensure skipped dataset={name}: user context unavailable")
            return
        canonical = self._resolve_dataset_alias(name)
        try:
            from cognee.modules.data.methods import get_authorized_dataset_by_name, create_authorized_dataset
        except Exception:
            return
        retried_setup = False
        while True:
            try:
                exists = await get_authorized_dataset_by_name(canonical, user_ctx, "write")
                if exists is not None:
                    identifier = self._extract_dataset_identifier(exists)
                    if identifier:
                        self.register_dataset_identifier(canonical, identifier)
                    return
                created = await create_authorized_dataset(canonical, user_ctx)
                identifier = self._extract_dataset_identifier(created)
                if identifier:
                    self.register_dataset_identifier(canonical, identifier)
                return
            except Exception as exc:
                if _needs_cognee_setup(exc) and not retried_setup:
                    from ai_coach.agent.knowledge.cognee_config import ensure_cognee_ready

                    retried_setup = True
                    await ensure_cognee_ready()
                    continue
                if _needs_cognee_setup(exc):
                    logger.warning(f"knowledge_dataset_ensure_failed dataset={canonical} detail={exc}")
                    return
                raise

    async def list_dataset_entries(self, dataset: str, user_ctx: Any | None) -> list[DatasetRow]:
        alias = self.alias_for_dataset(dataset)
        datasets_module = getattr(cognee, "datasets", None)
        if datasets_module is None:
            logger.debug(f"knowledge_dataset_list_skipped dataset={alias}: datasets module missing")
            raise ProjectionProbeError("datasets module missing")
        list_data = getattr(datasets_module, "list_data", None)
        if not callable(list_data):
            logger.debug(f"knowledge_dataset_list_skipped dataset={alias}: list_data missing")
            raise ProjectionProbeError("list_data missing")
        try:
            await self.ensure_dataset_exists(alias, user_ctx)
        except Exception as exc:
            logger.debug(f"knowledge_dataset_ensure_failed dataset={alias} detail={exc}")
            raise ProjectionProbeError(f"ensure_dataset_exists failed: {exc}") from exc
        try:
            rows = await self._fetch_dataset_rows(
                cast(Callable[..., Awaitable[Iterable[Any]]], list_data),
                alias,
                user_ctx,
            )
        except Exception as exc:
            logger.debug(f"knowledge_dataset_list_failed dataset={alias} detail={exc}")
            raise ProjectionProbeError(f"fetch_dataset_rows failed: {exc}") from exc
        rows_data: list[DatasetRow] = []
        for raw_row in rows:
            prepared = self._prepare_dataset_row(raw_row, alias)
            normalized = self._normalize_text(prepared.text)
            if not normalized:
                continue
            rows_data.append(DatasetRow(text=normalized, metadata=prepared.metadata))
        return rows_data

    async def _fetch_dataset_rows(
        self,
        list_data: Callable[..., Awaitable[Iterable[Any]]],
        dataset: str,
        user: Any | None,
    ) -> list[Any]:
        alias = self.alias_for_dataset(dataset)
        user_ctx = self.to_user_ctx(user)
        dataset_id = await self.get_dataset_id(dataset, user_ctx)
        if dataset_id is None:
            self.log_once(
                logging.WARNING,
                "projection:dataset_id_unavailable",
                dataset=alias,
                reason="dataset_id_unavailable",
            )
            raise ProjectionProbeError(f"dataset_id_unavailable alias={alias}")

        if user_ctx is not None:
            if self._list_data_supports_user is None or self._list_data_requires_user is None:
                supports, requires = self._describe_list_data(list_data)
                if supports is not None:
                    self._list_data_supports_user = supports
                if requires is not None:
                    self._list_data_requires_user = requires

        if user_ctx is not None and self._list_data_supports_user is not False:
            try:
                rows = await list_data(dataset_id, user=user_ctx)
            except TypeError:
                logger.debug("cognee.datasets.list_data rejected keyword 'user', retrying without keyword")
                self._list_data_supports_user = False
                if self._list_data_requires_user:
                    logger.debug("cognee.datasets.list_data requires user context, retrying positional call")
                    rows = await list_data(dataset_id, user_ctx)
                    self._list_data_supports_user = True
                    return list(rows)
            else:
                self._list_data_supports_user = True
                return list(rows)

        if user_ctx is not None and self._list_data_requires_user:
            rows = await list_data(dataset_id, user_ctx)
            self._list_data_supports_user = True
            return list(rows)

        try:
            rows = await list_data(dataset_id)
        except TypeError as exc:
            if user_ctx is not None:
                logger.debug(
                    f"cognee.datasets.list_data raised {exc.__class__.__name__}: retrying with positional user"
                )
                rows = await list_data(dataset_id, user_ctx)
                self._list_data_supports_user = True
                self._list_data_requires_user = True
                return list(rows)
            raise
        return list(rows)

    def _describe_list_data(
        self, list_data: Callable[..., Awaitable[Iterable[Any]]]
    ) -> tuple[bool | None, bool | None]:
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

    def to_user_ctx(self, user: Any | None) -> Any | None:
        if isinstance(user, SimpleNamespace) and isinstance(getattr(user, "id", None), UUID):
            tenant_value = getattr(user, "tenant_id", None)
            if tenant_value is None or isinstance(tenant_value, UUID):
                return user
        if user is None:
            return None

        raw_id = getattr(user, "id", None)
        if raw_id is None and isinstance(user, CogneeUser):
            from dataclasses import asdict

            payload = asdict(user)
            raw_id = payload.get("id")
            tenant_val = payload.get("tenant_id")
        elif raw_id is None and is_dataclass(user):
            from dataclasses import asdict

            payload = asdict(user)
            raw_id = payload.get("id")
            tenant_val = payload.get("tenant_id")
        else:
            tenant_val = getattr(user, "tenant_id", None)

        uid = self._normalize_uuid(raw_id)
        if uid is None:
            return None
        tenant_uuid = self._normalize_uuid(tenant_val)
        return SimpleNamespace(id=uid, tenant_id=tenant_uuid)

    def to_user_id(self, user: Any | None) -> str | None:
        user_ctx = self.to_user_ctx(user)
        return user_ctx.id.hex if user_ctx else None

    async def get_cognee_user(self) -> Any | None:
        if self._user is not None:
            return self._user
        retried_setup = False
        while True:
            try:
                from cognee.modules.users.methods.get_default_user import get_default_user

                self._user = await get_default_user()
                if self._user is None:
                    self._user = self._bootstrap_user_ctx()
                return self._user
            except Exception as exc:
                if _needs_cognee_setup(exc) and not retried_setup:
                    from ai_coach.agent.knowledge.cognee_config import ensure_cognee_ready

                    retried_setup = True
                    await ensure_cognee_ready()
                    continue
                if _needs_cognee_setup(exc):
                    self.log_once(
                        logging.WARNING,
                        "cognee:bootstrap_user",
                        reason="db_unavailable",
                        detail=str(exc),
                        min_interval=3600.0,
                    )
                    self._user = self._bootstrap_user_ctx()
                    return self._user
                logger.debug(f"cognee_user_fetch_failed detail={exc}")
                self._user = self._bootstrap_user_ctx()
                return self._user

    def _bootstrap_user_ctx(self) -> SimpleNamespace:
        return SimpleNamespace(id=self._BOOTSTRAP_USER_UUID, tenant_id=None)

    def log_once(self, level: int, event: str, **fields) -> None:
        ttl_value = fields.pop("ttl", None)
        min_interval = float(cast(float, fields.pop("min_interval", 10.0)))
        effective_ttl = float(ttl_value) if ttl_value is not None else min_interval
        throttle_key = fields.pop("throttle_key", event)
        global_log_once(
            throttle_key,
            level=level,
            ttl=effective_ttl,
            message=event,
            **fields,
        )

    def get_dataset_alias_count(self) -> int:
        return len(self._DATASET_ALIASES)

    def _resolve_dataset_alias(self, name: str) -> str:
        normalized = name.strip()
        if not normalized:
            return name
        if normalized.startswith("kb_client_"):
            suffix = normalized[len("kb_client_") :]
            try:
                client_id = int(suffix)
            except ValueError:
                return normalized
            return self.dataset_name(client_id)
        if normalized.startswith("client_"):
            suffix = normalized[len("client_") :]
            try:
                client_id = int(suffix)
            except ValueError:
                return normalized
            return self.dataset_name(client_id)
        return normalized

    def add_projected_dataset(self, alias: str) -> None:
        self._PROJECTED_DATASETS.add(alias)

    def dataset_name(self, client_id: int) -> str:
        return f"kb_client_{client_id}"

    def chat_dataset_name(self, client_id: int) -> str:
        return f"kb_chat_{client_id}"

    def is_chat_dataset(self, dataset: str) -> bool:
        alias = self.alias_for_dataset(dataset)
        return alias.startswith("kb_chat_")

    async def get_row_count(self, dataset: str, user: Any | None = None) -> int:
        raw_name = (dataset or "").strip()
        alias = self.resolve_dataset_alias(raw_name)
        names_to_check: list[str] = []
        if raw_name and raw_name != alias:
            names_to_check.append(raw_name)
        if alias:
            names_to_check.append(alias)
        elif raw_name:
            names_to_check.append(raw_name)

        hash_store = None
        try:
            from ai_coach.agent.knowledge.utils.hash_store import HashStore  # noqa: PLC0415
        except Exception:
            hash_store = None
        else:
            hash_store = HashStore

        if hash_store is not None:
            for name in names_to_check:
                try:
                    hash_count = await hash_store.count(name)
                except Exception:
                    hash_count = 0
                if hash_count:
                    return hash_count

        user_ctx = self.to_user_ctx(user)
        if user_ctx is None:
            user_ctx = self.to_user_ctx(await self.get_cognee_user())

        metadata = await self._get_dataset_metadata(alias, user_ctx)
        if metadata is None and raw_name and raw_name != alias:
            metadata = await self._get_dataset_metadata(raw_name, user_ctx)
        if metadata is None:
            return 0

        keys = (
            "rows",
            "rows_count",
            "rowsCount",
            "entries",
            "entries_count",
            "entriesCount",
            "documents",
            "documentsCount",
            "documents_count",
        )
        for key in keys:
            value = None
            if isinstance(metadata, Mapping):
                value = metadata.get(key)
            else:
                value = getattr(metadata, key, None)
            if value in (None, ""):
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return 0

    async def _get_dataset_metadata(self, dataset: str, user_ctx: Any | None) -> Any | None:
        try:
            from cognee.modules.data.methods import get_authorized_dataset_by_name
        except Exception:
            return None
        try:
            return await get_authorized_dataset_by_name(dataset, user_ctx, "read")
        except Exception as exc:
            logger.debug(f"knowledge_dataset_metadata_failed dataset={dataset} detail={exc}")
            return None

    def _normalize_uuid(self, value: Any | None) -> UUID | None:
        if value in (None, ""):
            return None
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except Exception:
            return uuid5(NAMESPACE_DNS, str(value))

    def _looks_like_uuid(self, value: str) -> bool:
        try:
            UUID(value)
        except (ValueError, TypeError):
            return False
        return True

    async def get_row_count_text(self, dataset: str, user: Any | None = None) -> int:
        return await self.get_row_count(dataset, user=user)

    async def get_row_count_chunks(self, dataset: str, user: Any | None = None) -> int:
        try:
            import cognee  # type: ignore

            datasets_module = getattr(cognee, "datasets", None)
            if datasets_module is None:
                return 0
            # Best-effort: if metadata exposes document count only, reuse it
            return await self.get_row_count(dataset, user=user)
        except Exception:
            return 0

    async def get_graph_counts(self, dataset: str, user: Any | None = None) -> tuple[int, int]:
        try:
            import cognee  # type: ignore

            graphs_module = getattr(cognee, "graphs", None)
            if graphs_module is None:
                return 0, 0
            # If no direct API, return zeros; adjust when graph API is available
            return 0, 0
        except Exception:
            return 0, 0

    async def get_counts(self, dataset: str, user: Any | None = None) -> dict[str, int]:
        raw_name = (dataset or "").strip()
        alias = self.alias_for_dataset(raw_name)
        identifier = await self.get_dataset_id(raw_name, user)

        names_to_check = list(dict.fromkeys([n for n in [raw_name, alias, identifier] if n]))

        text_rows = 0
        chunk_rows = 0
        nodes = 0
        edges = 0

        for name in names_to_check:
            text_rows = await self.get_row_count_text(name, user=user)
            if text_rows > 0:
                chunk_rows = await self.get_row_count_chunks(name, user=user)
                nodes, edges = await self.get_graph_counts(name, user=user)
                break

        return {
            "text_rows": int(text_rows or 0),
            "chunk_rows": int(chunk_rows or 0),
            "graph_nodes": int(nodes or 0),
            "graph_edges": int(edges or 0),
        }

    def _prepare_dataset_row(self, raw: Any, alias: str) -> DatasetRow:
        from ai_coach.agent.knowledge.utils.storage import StorageService

        text_value = getattr(raw, "text", None)
        if not isinstance(text_value, str):
            if isinstance(text_value, (int, float, bool)):
                base_text = str(text_value)
            else:
                if text_value is not None:
                    self.log_once(
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
        metadata_map = self._coerce_metadata(metadata_obj)
        digest_sha_meta = StorageService.metadata_digest_sha(metadata_map)
        normalized_text = self._normalize_text(base_text)
        if not normalized_text and digest_sha_meta:
            storage_text = StorageService.read_storage_text(digest_sha=digest_sha_meta)
            if storage_text is not None:
                normalized_text = self._normalize_text(storage_text)
        metadata_dict: dict[str, Any] | None = dict(metadata_map) if metadata_map else None
        if metadata_dict is not None:
            metadata_dict.setdefault("dataset", alias)
        text_output = normalized_text if normalized_text else base_text
        if not normalized_text:
            self.log_once(
                logging.INFO,
                "knowledge_dataset_row_empty",
                dataset=alias,
                digest=digest_sha_meta[:12] if digest_sha_meta else "N/A",
                reason="empty_content",
                ttl=300.0,
            )
            logger.debug(
                "knowledge_dataset_row_empty dataset={} digest={} reason=empty_content".format(
                    alias,
                    (digest_sha_meta[:12] if digest_sha_meta else "N/A"),
                )
            )
        if normalized_text:
            digest_sha = StorageService.compute_digests(normalized_text, dataset_alias=alias)
            if metadata_dict is None:
                metadata_dict = {"dataset": alias}
            metadata_dict.setdefault("digest_sha", digest_sha)
        if metadata_dict and not metadata_dict.get("dataset"):
            metadata_dict["dataset"] = alias
        if metadata_dict is not None and not metadata_dict:
            metadata_dict = None
        return DatasetRow(text=text_output, metadata=metadata_dict)

    def _coerce_metadata(self, meta: Any) -> Mapping[str, Any] | None:
        from dataclasses import asdict, is_dataclass

        if meta is None:
            return None
        if isinstance(meta, Mapping):
            return dict(meta)
        if is_dataclass(meta):
            return asdict(meta)
        try:
            return dict(meta)
        except Exception:
            return None

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        from ai_coach.agent.knowledge.utils.helpers import normalize_text

        return normalize_text(value)

    @staticmethod
    def _infer_metadata_from_text(text: str, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
        from ai_coach.types import MessageRole

        normalized = DatasetService._normalize_text(text)
        payload: dict[str, Any] = {}
        if extra:
            payload.update(dict(extra))
        if not normalized.strip():
            return payload

        encoded = normalized.encode("utf-8")
        payload["bytes"] = len(encoded)
        payload["digest_sha"] = hashlib.sha256(encoded).hexdigest()
        payload["preview"] = normalized[:120]

        if "kind" not in payload:
            trimmed = normalized.strip()
            lower = trimmed.casefold()
            for role in MessageRole:
                prefix = f"{role.value}:".casefold()
                if lower.startswith(prefix):
                    payload["kind"] = "message"
                    payload.setdefault("role", role.value)
                    break
            else:
                payload["kind"] = "document"
        else:
            payload["kind"] = str(payload["kind"]).lower()
        return payload
