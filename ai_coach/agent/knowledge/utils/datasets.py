import asyncio
from hashlib import sha256
import inspect
import logging
from dataclasses import is_dataclass
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, ClassVar, Iterable, Mapping, Optional, cast
from uuid import NAMESPACE_DNS, UUID, uuid5

from sqlalchemy.exc import MultipleResultsFound
from loguru import logger

import cognee

from ai_coach.agent.knowledge.schemas import DatasetRow
from ai_coach.exceptions import ProjectionProbeError
from ai_coach.schemas import CogneeUser
from ai_coach.agent.knowledge.utils.helpers import needs_cognee_setup
from config.app_settings import settings
from ai_coach.logging_config import log_once as global_log_once


class DatasetService:
    _DATASET_IDS: ClassVar[dict[str, str]] = {}
    _DATASET_ALIASES: ClassVar[dict[str, str]] = {}
    _PROJECTED_DATASETS: ClassVar[set[str]] = set()
    _DATASET_IDENTIFIER_FIELDS: ClassVar[tuple[str, ...]] = (
        "id",
        "dataset_id",
        "datasetId",
        "dataset_name",
        "datasetName",
    )
    _BOOTSTRAP_USER_UUID: ClassVar[UUID] = uuid5(NAMESPACE_DNS, "gymbot_cognee_bootstrap_user")
    GLOBAL_DATASET: ClassVar[str] = settings.COGNEE_GLOBAL_DATASET

    def __init__(self, storage_service: Any | None = None):
        type(self).GLOBAL_DATASET = settings.COGNEE_GLOBAL_DATASET
        self._user: Any | None = None
        self._list_data_supports_user: bool | None = None
        self._list_data_requires_user: bool | None = None
        self._storage_service = storage_service
        self._graph_engine: Any | None = None

    def set_storage_service(self, storage_service: Any) -> None:
        if self._storage_service is not None:
            logger.warning("DatasetService storage service already set, overwriting.")
        self._storage_service = storage_service

    def set_graph_engine(self, engine: Any | None) -> None:
        self._graph_engine = engine
        if engine is not None:
            attrs = [name for name in dir(engine) if not name.startswith("_")]
            logger.info(
                "cognee_graph_engine_attached type={} attrs_sample={} total_attrs={}",
                type(engine),
                attrs[:20],
                len(attrs),
            )

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
        self._DATASET_ALIASES[identifier] = canonical
        if self._looks_like_uuid(identifier):
            self._DATASET_IDS[canonical] = identifier

    @staticmethod
    def _is_duplicate_dataset_error(exc: Exception) -> bool:
        text = str(exc).lower()
        if "duplicate key value violates unique constraint" in text and "datasets" in text:
            return True
        if exc.__class__.__name__.lower().startswith("uniqueviolation"):
            return True
        return False

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
                effective_ctx = self.to_user_ctx(user_ctx)
                if effective_ctx:
                    await self.ensure_dataset_exists(alias, effective_ctx)
                    identifier = self._DATASET_IDS.get(alias)
                    if identifier:
                        self.log_once(logging.DEBUG, "dataset_resolved", name=alias, id=identifier, min_interval=5.0)
                        return identifier
            except Exception as exc:
                logger.debug(f"knowledge_dataset_id_lookup_failed dataset={alias} detail={exc}")

        if user_ctx is not None:
            effective_ctx = self.to_user_ctx(user_ctx)
            if effective_ctx:
                metadata = await self._get_dataset_metadata(alias, effective_ctx)
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

    async def get_dataset_uuid(self, dataset: str, user_ctx: Any | None) -> UUID | None:
        alias = self.alias_for_dataset(dataset)
        meta = await self._get_dataset_metadata(alias, self.to_user_ctx_or_default(user_ctx))
        candidate: Any = None
        if isinstance(meta, Mapping):
            candidate = meta.get("id") or meta.get("dataset_id") or meta.get("datasetId")
        else:
            candidate = getattr(meta, "id", None) or getattr(meta, "dataset_id", None)
        resolved_uuid: UUID | None = None
        if candidate:
            try:
                resolved_uuid = candidate if isinstance(candidate, UUID) else UUID(str(candidate))
            except Exception:
                logger.debug(f"dataset_uuid_invalid dataset={alias} value={candidate}")
        if resolved_uuid is None:
            resolved_uuid = await self._fetch_dataset_uuid_from_db(alias)
        if resolved_uuid is not None:
            self.register_dataset_identifier(alias, str(resolved_uuid))
            return resolved_uuid
        logger.debug(f"dataset_uuid_unavailable dataset={alias}")
        return None

    async def reset_pipeline_status(self, dataset_id: str | UUID | None, pipeline_name: str) -> None:
        if not dataset_id:
            return
        try:
            from sqlalchemy import delete, select
            from cognee.infrastructure.databases.relational import get_relational_engine
            from cognee.modules.data.models import Data, DatasetData
            from cognee.modules.pipelines.models import PipelineRun
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"pipeline_status_reset_skipped dataset_id={dataset_id} detail={exc}")
            return

        try:
            dataset_uuid = dataset_id if isinstance(dataset_id, UUID) else UUID(str(dataset_id))
        except Exception:
            logger.debug(f"pipeline_status_reset_invalid_id dataset_id={dataset_id}")
            return

        db_engine = get_relational_engine()
        cleared_items = 0
        async with db_engine.get_async_session() as session:
            await session.execute(
                delete(PipelineRun).where(
                    PipelineRun.dataset_id == dataset_uuid,
                    PipelineRun.pipeline_name == pipeline_name,
                )
            )
            result = await session.execute(
                select(Data)
                .join(DatasetData, Data.id == DatasetData.data_id)
                .where(DatasetData.dataset_id == dataset_uuid)
            )
            records = result.scalars().all()
            for item in records:
                status_map = item.pipeline_status or {}
                entry = status_map.get(pipeline_name)
                if not isinstance(entry, dict):
                    continue
                if entry.pop(str(dataset_uuid), None) is None:
                    continue
                if entry:
                    status_map[pipeline_name] = entry
                else:
                    status_map.pop(pipeline_name, None)
                item.pipeline_status = status_map
                cleared_items += 1
            await session.commit()
        logger.debug(
            f"pipeline_status_reset_done dataset_id={dataset_uuid} pipeline={pipeline_name} items={cleared_items}"
        )

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
        ctx = self.to_user_ctx_or_default(user_ctx)
        user_id = getattr(ctx, "id", None)
        alias = self.alias_for_dataset(name)

        canonical = self._resolve_dataset_alias(name)
        try:
            from cognee.modules.data.methods import get_authorized_dataset_by_name, create_authorized_dataset
        except Exception:
            raise RuntimeError("cognee_modules_unavailable")

        attempts = 0
        while True:
            attempts += 1
            try:
                exists = await get_authorized_dataset_by_name(canonical, ctx, "write")
                if exists is not None:
                    identifier = self._extract_dataset_identifier(exists)
                    logger.debug(f"dataset.ensure_exists.found alias={alias} user_id={user_id} ident={identifier}")
                    if identifier:
                        self.register_dataset_identifier(canonical, identifier)
                    await self._sync_dataset_uuid_from_db(canonical)
                    return
                logger.debug(f"knowledge_dataset_creating dataset={alias} user_id={user_id}")
                created = await create_authorized_dataset(canonical, ctx)
                identifier = self._extract_dataset_identifier(created)
                logger.debug(f"knowledge_dataset_created dataset={alias} user_id={user_id} ident={identifier}")
                if identifier:
                    self.register_dataset_identifier(canonical, identifier)
                await self._sync_dataset_uuid_from_db(canonical)
                return
            except MultipleResultsFound as exc:
                healed = await self._heal_duplicate_datasets(canonical)
                if healed:
                    logger.warning(
                        "knowledge_dataset_duplicate_healed alias={} user_id={} attempts={} detail={}",
                        alias,
                        user_id,
                        attempts,
                        exc,
                    )
                    continue
                raise
            except Exception as exc:
                if needs_cognee_setup(exc):
                    logger.warning(f"knowledge_dataset_ensure_failed dataset={canonical} detail={exc}")
                    raise RuntimeError(f"cognee_setup_failed: {exc}") from exc
                if self._is_duplicate_dataset_error(exc):
                    logger.info(
                        "knowledge_dataset_create_duplicate alias={} user_id={} attempt={} detail={}",
                        alias,
                        user_id,
                        attempts,
                        exc,
                    )
                    await asyncio.sleep(0.2)
                    continue
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

        normalized_user = self.to_user_ctx_or_default(user_ctx)
        user_id_str = str(normalized_user.id)

        logger.debug(f"dataset.list_entries.start alias={alias} raw_user={user_id_str}")

        try:
            await self.ensure_dataset_exists(alias, normalized_user)
        except Exception as exc:
            logger.debug(f"knowledge_dataset_ensure_failed dataset={alias} detail={exc}")
            raise ProjectionProbeError(f"ensure_dataset_exists failed: {exc}") from exc

        try:
            await self.get_dataset_id(alias, normalized_user)
        except Exception as exc:
            logger.debug(f"knowledge_dataset_get_id_failed dataset={alias} user={user_id_str} detail={exc}")
            raise ProjectionProbeError(f"get_dataset_id failed: {exc}") from exc

        try:
            rows = await self._fetch_dataset_rows(
                cast(Callable[..., Awaitable[Iterable[Any]]], list_data),
                alias,
                normalized_user,
            )
            logger.debug(f"dataset.list_entries.fetched alias={alias} rows_raw={len(rows)}")
        except Exception as exc:
            logger.debug(f"knowledge_dataset_list_failed dataset={alias} user={user_id_str} detail={exc}")
            raise ProjectionProbeError(f"fetch_dataset_rows failed: {exc}") from exc

        rows_data: list[DatasetRow] = []
        for index, raw_row in enumerate(rows):
            prepared = await self._prepare_dataset_row(raw_row, alias)
            normalized_text = self._normalize_text(prepared.text)

            if not normalized_text:
                digest = prepared.metadata.get("digest_sha") if prepared.metadata else "N/A"
                if index < 50:
                    logger.debug(
                        f"dataset.list_entries.drop_empty_row alias={alias} user={user_id_str} "
                        f"index={index} digest={digest} text_len={len(prepared.text or '')}"
                    )
                continue

            if index < 2:
                preview = normalized_text.replace("\n", " ")[:80]
                digest = prepared.metadata.get("digest_sha") if prepared.metadata else "N/A"
                logger.debug(
                    (
                        f"dataset.list_entries.sample alias={alias} index={index} digest={digest} "
                        f"text_preview='{preview}...'"
                    )
                )

            rows_data.append(DatasetRow(text=normalized_text, metadata=prepared.metadata))

        logger.debug(f"dataset.list_entries.result alias={alias} rows_nonempty={len(rows_data)}")
        return rows_data

    async def _fetch_dataset_rows(
        self,
        list_data: Callable[..., Awaitable[Iterable[Any]]],
        dataset: str,
        user: Any | None,
    ) -> list[Any]:
        alias = self.alias_for_dataset(dataset)
        user_ctx = self.to_user_ctx_or_default(user)

        # Log before calling list_data as requested
        logger.debug(f"knowledge_fetch_dataset_rows dataset={alias} user_id={user_ctx.id}")

        dataset_id = await self.get_dataset_id(dataset, user_ctx)
        if dataset_id is None:
            self.log_once(
                logging.WARNING,
                "projection:dataset_id_unavailable",
                dataset=alias,
                reason="dataset_id_unavailable",
            )
            raise ProjectionProbeError(f"dataset_id_unavailable alias={alias}")

        if self._list_data_supports_user is None or self._list_data_requires_user is None:
            supports, requires = self._describe_list_data(list_data)
            if supports is not None:
                self._list_data_supports_user = supports
            if requires is not None:
                self._list_data_requires_user = requires

        logger.debug(
            f"dataset.fetch_rows.call alias={alias} dataset_id={dataset_id} "
            f"user_id={user_ctx.id} signature_support_user={self._list_data_supports_user} "
            f"requires_user={self._list_data_requires_user}"
        )

        rows = await self._call_list_data(list_data, dataset_id, user_ctx)
        if not rows and dataset_id != alias and not self._looks_like_uuid(str(dataset_id)):
            logger.debug(
                "dataset.fetch_rows.retry alias={} dataset_id={} reason=empty_rows",
                alias,
                dataset_id,
            )
            try:
                rows = await self._call_list_data(list_data, alias, user_ctx)
            except Exception as exc:
                self.log_once(
                    logging.WARNING,
                    "dataset.fetch_rows_retry_failed",
                    dataset=alias,
                    reason="alias_not_supported",
                    detail=str(exc),
                    min_interval=30.0,
                )
        return list(rows)

    async def _call_list_data(
        self,
        list_data: Callable[..., Awaitable[Iterable[Any]]],
        target: str,
        user_ctx: Any,
    ) -> list[Any]:
        if self._list_data_supports_user is not False:
            try:
                rows = await list_data(target, user=user_ctx)
            except TypeError:
                logger.debug("cognee.datasets.list_data rejected keyword 'user', retrying without keyword")
                self._list_data_supports_user = False
                if self._list_data_requires_user:
                    logger.debug("cognee.datasets.list_data requires user context, retrying positional call")
                    rows = await list_data(target, user_ctx)
                    self._list_data_supports_user = True
                    return list(rows)
            else:
                self._list_data_supports_user = True
                return list(rows)

        if self._list_data_requires_user:
            rows = await list_data(target, user_ctx)
            self._list_data_supports_user = True
            return list(rows)

        try:
            rows = await list_data(target)
        except TypeError as exc:
            logger.debug(f"cognee.datasets.list_data raised {exc.__class__.__name__}: retrying with positional user")
            rows = await list_data(target, user_ctx)
            self._list_data_supports_user = True
            self._list_data_requires_user = True
            return list(rows)
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

    def to_user_ctx_or_default(self, user: Any | None) -> Any:
        ctx = self.to_user_ctx(user)
        if ctx is not None:
            return ctx

        # Fallback logic as requested
        if self._user is not None:
            return self._user

        # Last resort: bootstrap
        # Note: We don't try async get_cognee_user() here because this method is sync.
        # This matches the requirement to use existing helpers but ensuring non-None.
        # If we really need the fully initialized default user, we should have probably
        # initialized it earlier or accept that this fallback is sufficient.
        # Checks: If _bootstrap_user_ctx gives us a valid ID, that's usually enough.
        return self._bootstrap_user_ctx()

    def to_user_id(self, user: Any | None) -> str | None:
        user_ctx = self.to_user_ctx(user)
        return user_ctx.id.hex if user_ctx else None

    async def get_cognee_user(self) -> Any | None:
        if self._user is not None:
            return self._user
        while True:
            try:
                from cognee.modules.users.methods.get_default_user import get_default_user

                self._user = await get_default_user()
                if self._user is None:
                    self._user = self._bootstrap_user_ctx()
                return self._user
            except Exception as exc:
                if needs_cognee_setup(exc):
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
        if normalized.startswith("kb_profile_"):
            suffix = normalized[len("kb_profile_") :]
            try:
                profile_id = int(suffix)
            except ValueError:
                return normalized
            return self.dataset_name(profile_id)
        if normalized.startswith("client_"):
            suffix = normalized[len("client_") :]
            try:
                profile_id = int(suffix)
            except ValueError:
                return normalized
            return self.dataset_name(profile_id)
        if normalized.startswith("profile_"):
            suffix = normalized[len("profile_") :]
            try:
                profile_id = int(suffix)
            except ValueError:
                return normalized
            return self.dataset_name(profile_id)
        return normalized

    def add_projected_dataset(self, alias: str) -> None:
        self._PROJECTED_DATASETS.add(alias)

    def dataset_name(self, profile_id: int) -> str:
        return f"kb_profile_{profile_id}"

    def chat_dataset_name(self, profile_id: int) -> str:
        return f"kb_chat_{profile_id}"

    def session_id_for_profile(self, profile_id: int) -> str:
        return self.chat_dataset_name(profile_id)

    def is_chat_dataset(self, dataset: str) -> bool:
        alias = self.alias_for_dataset(dataset)
        return alias.startswith("kb_chat_")

    def forget_dataset(self, dataset: str) -> None:
        alias = self.alias_for_dataset(dataset)
        identifier = self._DATASET_IDS.pop(alias, None) if alias else None
        self._PROJECTED_DATASETS.discard(alias)
        if identifier:
            self._DATASET_ALIASES.pop(identifier, None)
        keys_to_remove: list[str] = []
        for key, value in self._DATASET_ALIASES.items():
            if key == alias or value == alias:
                keys_to_remove.append(key)
        for key in keys_to_remove:
            self._DATASET_ALIASES.pop(key, None)

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

    async def _fetch_dataset_uuid_from_db(self, alias: str, *, allow_heal: bool = True) -> UUID | None:
        try:
            from sqlalchemy import select
            from cognee.modules.data.models import Dataset
            from cognee.infrastructure.databases.relational import get_relational_engine
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"dataset_uuid_fallback_unavailable dataset={alias} detail={exc}")
            return None

        engine = get_relational_engine()
        candidate_names: list[str] = []
        identifier = self._DATASET_IDS.get(alias)
        if identifier and identifier not in candidate_names:
            candidate_names.append(identifier)
        if alias not in candidate_names:
            candidate_names.append(alias)
        if not candidate_names:
            return None

        async with engine.get_async_session() as session:
            result = await session.execute(
                select(Dataset).where(Dataset.name.in_(candidate_names)).order_by(Dataset.created_at)
            )
            rows = result.scalars().all()

        if not rows:
            return None

        if len(rows) > 1:
            self.log_once(
                logging.WARNING,
                "dataset_uuid_multiple_rows",
                dataset=alias,
                candidates=",".join(candidate_names),
                rows=len(rows),
                min_interval=30.0,
            )
            if allow_heal:
                healed = await self._heal_duplicate_dataset_rows(rows, alias, candidate_names=candidate_names)
                if healed:
                    return await self._fetch_dataset_uuid_from_db(alias, allow_heal=False)

        raw_id = rows[0].id
        try:
            return raw_id if isinstance(raw_id, UUID) else UUID(str(raw_id))
        except Exception:
            logger.debug(f"dataset_uuid_db_invalid dataset={alias} value={raw_id}")
            return None

    async def _heal_duplicate_dataset_rows(
        self,
        rows: list[Any],
        alias: str,
        *,
        candidate_names: Iterable[str],
    ) -> bool:
        if len(rows) <= 1:
            return False
        try:
            from sqlalchemy import delete
            from cognee.infrastructure.databases.relational import get_relational_engine
            from cognee.modules.data.models import Dataset, DatasetData
            from cognee.modules.pipelines.models import PipelineRun
            from cognee.modules.users.models import ACL
        except Exception as exc:  # noqa: BLE001
            logger.warning("knowledge_dataset_duplicate_cleanup_unavailable alias={} detail={}", alias, exc)
            return False

        survivor = rows[0]
        duplicate_ids = [row.id for row in rows[1:] if row.id is not None]
        if not duplicate_ids:
            logger.warning(
                "knowledge_dataset_duplicate_cleanup_failed alias={} reason=missing_duplicate_ids",
                alias,
            )
            return False

        engine = get_relational_engine()
        async with engine.get_async_session() as session:
            await session.execute(delete(DatasetData).where(DatasetData.dataset_id.in_(duplicate_ids)))
            await session.execute(delete(PipelineRun).where(PipelineRun.dataset_id.in_(duplicate_ids)))
            await session.execute(delete(ACL).where(ACL.dataset_id.in_(duplicate_ids)))
            await session.execute(delete(Dataset).where(Dataset.id.in_(duplicate_ids)))
            await session.commit()

        logger.warning(
            "knowledge_dataset_duplicate_cleanup alias={} kept_id={} removed={} candidates={}",
            alias,
            survivor.id,
            ", ".join(str(value) for value in duplicate_ids),
            ",".join(candidate_names),
        )
        await self._sync_dataset_uuid_from_db(alias)
        return True

    async def _sync_dataset_uuid_from_db(self, alias: str) -> str | None:
        canonical = self._resolve_dataset_alias(alias)
        if not canonical:
            return None
        actual_uuid = await self._fetch_dataset_uuid_from_db(canonical)
        if actual_uuid is None:
            return None
        identifier = str(actual_uuid)
        self._DATASET_IDS[canonical] = identifier
        self._DATASET_ALIASES[identifier] = canonical
        return identifier

    async def _heal_duplicate_datasets(self, alias: str) -> bool:
        canonical = self._resolve_dataset_alias(alias)
        if not canonical:
            return False
        try:
            from sqlalchemy import select
            from cognee.infrastructure.databases.relational import get_relational_engine
            from cognee.modules.data.models import Dataset
        except Exception as exc:  # noqa: BLE001
            logger.warning("knowledge_dataset_duplicate_cleanup_unavailable alias={} detail={}", canonical, exc)
            return False

        engine = get_relational_engine()
        async with engine.get_async_session() as session:
            result = await session.execute(
                select(Dataset).where(Dataset.name == canonical).order_by(Dataset.created_at)
            )
            rows = result.scalars().all()
        return await self._heal_duplicate_dataset_rows(rows, canonical, candidate_names=[canonical])

    async def purge_dataset(self, alias: str, drop_all: bool = False) -> bool:
        canonical = self._resolve_dataset_alias(alias)
        if not canonical:
            return False
        try:
            from sqlalchemy import delete, select
            from cognee.infrastructure.databases.relational import get_relational_engine
            from cognee.modules.data.models import Dataset, DatasetData
            from cognee.modules.pipelines.models import PipelineRun
            from cognee.modules.users.models import ACL
        except Exception as exc:  # noqa: BLE001
            logger.warning("knowledge_dataset_purge_unavailable alias={} detail={}", canonical, exc)
            return False

        engine = get_relational_engine()
        async with engine.get_async_session() as session:
            result = await session.execute(
                select(Dataset).where(Dataset.name == canonical).order_by(Dataset.created_at)
            )
            primary_rows = result.scalars().all()
            if not primary_rows:
                return False

            candidate_names = {canonical}
            candidate_names.update(str(row.id) for row in primary_rows if row.id is not None)

            result = await session.execute(
                select(Dataset).where(Dataset.name.in_(candidate_names)).order_by(Dataset.created_at)
            )
            rows = result.scalars().all()
            if not rows:
                return False

            if drop_all:
                target_ids = [row.id for row in rows if row.id is not None]
            else:
                target_ids = [row.id for row in rows[1:] if row.id is not None]

            if not target_ids:
                return False

            await session.execute(delete(DatasetData).where(DatasetData.dataset_id.in_(target_ids)))
            await session.execute(delete(PipelineRun).where(PipelineRun.dataset_id.in_(target_ids)))
            await session.execute(delete(ACL).where(ACL.dataset_id.in_(target_ids)))
            await session.execute(delete(Dataset).where(Dataset.id.in_(target_ids)))
            await session.commit()

        action = "purged" if drop_all else "healed"
        logger.warning(
            "knowledge_dataset_purge alias={} action={} removed={}",
            canonical,
            action,
            ", ".join(str(value) for value in target_ids),
        )

        if drop_all:
            self._DATASET_IDS.pop(canonical, None)
            for identifier, value in list(self._DATASET_ALIASES.items()):
                if value == canonical:
                    self._DATASET_ALIASES.pop(identifier, None)
        await self._sync_dataset_uuid_from_db(canonical)
        return True

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
            alias = self.alias_for_dataset(dataset)
            user_ctx = self.to_user_ctx_or_default(user)
            metadata = await self._get_dataset_metadata(alias, user_ctx)
            if metadata is None:
                return 0

            # Common keys for chunk counts in metadata
            keys = (
                "chunk_rows",
                "chunks",
                "chunk_count",
                "embeddings_count",
                "vector_entries",
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

            # If no specific chunk count found, fallback to text rows as a heuristic
            logger.debug(f"cognee_chunk_count_fallback_text_rows dataset={alias}")
            return await self.get_row_count_text(dataset, user=user)
        except Exception as exc:
            logger.warning(f"cognee_chunk_counts_failed dataset={dataset} detail={exc}")
            return 0

    async def get_graph_counts(self, dataset: str, user: Any | None = None) -> tuple[int, int]:
        alias = self.alias_for_dataset(dataset)
        logger.debug(f"cognee_graph_counts.start dataset={alias}")
        graph_engine = self._graph_engine
        if graph_engine is None:
            logger.warning(f"cognee_graph_counts_unavailable dataset={alias} reason=missing_graph_engine")
            return 0, 0

        driver = getattr(graph_engine, "driver", None)
        if driver is None:
            logger.warning(f"cognee_graph_counts_unavailable dataset={alias} reason=missing_driver")
            return 0, 0

        try:
            nodes = await self._execute_graph_count(driver, "MATCH (n) RETURN count(n) AS count")
            edges = await self._execute_graph_count(driver, "MATCH ()-[r]->() RETURN count(r) AS count")
        except Exception as exc:
            logger.warning(f"cognee_graph_counts_failed dataset={alias} detail={exc}")
            return 0, 0

        if nodes == 0 and edges == 0:
            logger.debug(f"cognee_graph_counts_empty_global dataset={alias} nodes_total={nodes} edges_total={edges}")
        else:
            logger.debug(f"cognee_graph_counts_global dataset={alias} nodes_total={nodes} edges_total={edges}")
        return nodes, edges

    async def _execute_graph_count(self, driver: Any, query: str) -> int:
        session_factory = getattr(driver, "session", None)
        if session_factory is None or not callable(session_factory):
            raise RuntimeError("graph_driver_session_unavailable")

        kwargs: dict[str, Any] = {}
        graph_db_name = getattr(settings, "GRAPH_DATABASE_NAME", None)
        if graph_db_name:
            kwargs["database"] = graph_db_name

        session = session_factory(**kwargs)

        async def _fetch_count(handle: Any) -> int:
            result = handle.run(query)
            if hasattr(result, "__await__"):
                result = await result
            record = result.single()
            if hasattr(record, "__await__"):
                record = await record
            if record is None:
                return 0
            value = record.value()
            if hasattr(value, "__await__"):
                value = await value
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        if hasattr(session, "__aenter__") and hasattr(session, "__aexit__"):
            async with session as handle:
                return await _fetch_count(handle)
        if hasattr(session, "__enter__") and hasattr(session, "__exit__"):
            with session as handle:
                return await _fetch_count(handle)
        return await _fetch_count(session)

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

    async def _prepare_dataset_row(self, raw: Any, alias: str) -> DatasetRow:
        from ai_coach.agent.knowledge.utils.storage import StorageService

        text_value = getattr(raw, "text", None)
        if hasattr(raw, "text"):
            raw_len = len(str(text_value)) if text_value is not None else 0
            logger.debug(f"dataset.prepare_row raw_len={raw_len} alias={alias}")

        if isinstance(text_value, str):
            base_text = text_value
        elif isinstance(text_value, (int, float, bool)):
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

        metadata_obj = getattr(raw, "metadata", None)
        metadata_map = self._coerce_metadata(metadata_obj)
        digest_sha_meta = StorageService.metadata_digest_sha(metadata_map)
        content_hash_attr = getattr(raw, "content_hash", None)
        effective_digest = digest_sha_meta or content_hash_attr

        normalized_text = self._normalize_text(base_text)
        if not normalized_text and effective_digest:
            if self._storage_service is None:
                logger.error("StorageService not available in DatasetService for read_storage_text.")
            else:
                storage_text = await self._storage_service.read_storage_text(digest_sha=effective_digest)
                if storage_text is not None:
                    normalized_text = self._normalize_text(storage_text)

        metadata_dict: dict[str, Any] = dict(metadata_map) if metadata_map else {}
        metadata_dict.setdefault("dataset", alias)
        text_output = normalized_text if normalized_text else base_text

        if not normalized_text:
            self.log_once(
                logging.INFO,
                "knowledge_dataset_row_empty",
                dataset=alias,
                digest=(effective_digest[:12] if effective_digest else "N/A"),
                reason="empty_content",
                ttl=300.0,
            )
            logger.debug(
                "knowledge_dataset_row_empty dataset={} digest={} reason=empty_content".format(
                    alias,
                    (effective_digest[:12] if effective_digest else "N/A"),
                )
            )

        if normalized_text:
            if self._storage_service is None:
                logger.error("StorageService not available in DatasetService for compute_digests, using fallback.")
                digest_sha = sha256(self._normalize_text(normalized_text).encode("utf-8")).hexdigest()
            else:
                digest_sha = self._storage_service.compute_digests(normalized_text, dataset_alias=alias)
            metadata_dict.setdefault("digest_sha", digest_sha)

        if not metadata_dict:
            metadata_payload: dict[str, Any] | None = None
        else:
            metadata_payload = metadata_dict

        return DatasetRow(text=text_output, metadata=metadata_payload)

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

        in_len = len(value) if value is not None else -1
        result = normalize_text(value)
        out_len = len(result)
        if in_len > 0 and out_len == 0:
            logger.debug(f"dataset.normalize_text dropped content in_len={in_len}")
        return result

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
        payload["digest_sha"] = sha256(encoded).hexdigest()
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
