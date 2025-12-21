import asyncio
import os
import shutil
import sys
import types
from collections import defaultdict
from hashlib import md5, sha256
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, List, Mapping, Sequence, Set
from unittest.mock import patch as _patch
from uuid import uuid4
import pytest

from .stubs import *
import ai_coach.agent.knowledge.cognee_config as cognee_config
import ai_coach.agent.knowledge.gdrive_knowledge_loader as gdrive_loader_module
import ai_coach.agent.knowledge.knowledge_base as kb_module
from ai_coach.agent.knowledge.schemas import DatasetRow, KnowledgeSnippet, ProjectionStatus
import config.app_settings as app_settings
from core.services.internal import APIService
import django

kb_module.APIService = APIService

os.environ.setdefault("COGNEE_STORAGE_PATH", ".cognee_test_storage")
os.environ.setdefault("COGNEE_DATA_ROOT", ".cognee_test_storage")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.test_settings")


django.setup()

if "cognee" not in sys.modules:
    sys.modules["cognee"] = types.SimpleNamespace()

cognee_module = sys.modules["cognee"]

if not hasattr(cognee_module, "base_config"):
    base_config_stub = types.SimpleNamespace(get_base_config=lambda: types.SimpleNamespace(data_root_directory="."))
    sys.modules["cognee.base_config"] = base_config_stub
    cognee_module.base_config = base_config_stub

_PROD_DEFAULTS = app_settings.Settings(COGNEE_STORAGE_PATH=".cognee_test_storage")


@pytest.fixture(scope="session", autouse=True)
def _cognee_storage_cleanup() -> Iterable[None]:
    storage_path = Path(getattr(app_settings.settings, "COGNEE_STORAGE_PATH", ".cognee_test_storage"))
    if storage_path.exists():
        shutil.rmtree(storage_path, ignore_errors=True)
    yield
    if storage_path.exists():
        shutil.rmtree(storage_path, ignore_errors=True)


class _InMemoryHashStore:
    _store = defaultdict(dict)
    _meta = defaultdict(dict)

    @classmethod
    async def add(cls, dataset: str, digest: str, *, metadata: Mapping[str, Any] | None = None) -> None:
        cls._store[dataset][digest] = metadata or {}
        if metadata:
            cls._meta[dataset][digest] = metadata

    @classmethod
    async def contains(cls, dataset: str, digest: str) -> bool:
        return digest in cls._store.get(dataset, {})

    @classmethod
    async def list(cls, dataset: str) -> Set[str]:
        return set(cls._store.get(dataset, {}).keys())

    @classmethod
    async def metadata(cls, dataset: str, digest: str) -> Mapping[str, Any] | None:
        return cls._meta.get(dataset, {}).get(digest)

    @classmethod
    async def clear(cls, dataset: str) -> None:
        if dataset in cls._store:
            del cls._store[dataset]
        if dataset in cls._meta:
            del cls._meta[dataset]

    @classmethod
    async def list_all_datasets(cls) -> List[str]:
        return list(cls._store.keys())

    @classmethod
    async def get_md5_for_sha(cls, dataset: str, digest: str) -> str | None:
        meta = await cls.metadata(dataset, digest)
        if meta:
            return meta.get("digest_md5")
        return None


kb_module.HashStore = _InMemoryHashStore


@pytest.fixture(autouse=True)
def clear_hash_store():
    _InMemoryHashStore._store.clear()
    _InMemoryHashStore._meta.clear()
    yield


@pytest.fixture(autouse=True)
def reset_kb_class() -> Iterable[None]:
    yield
    kb_module.KnowledgeBase = _KB
    api_module.KnowledgeBase = _KB
    agent_tools_module.KnowledgeBase = _KB


class _DatasetService:
    def __init__(self):
        self._PROJECTED_DATASETS: set[str] = set()

    async def get_cognee_user(self):
        return types.SimpleNamespace(id=1)

    def alias_for_dataset(self, name: str) -> str:
        return name

    def log_once(self, *args, **kwargs) -> None:
        return None

    def chat_dataset_name(self, profile_id: int) -> str:
        return f"chat_{profile_id}"

    def to_user_ctx(self, user):
        return user or types.SimpleNamespace(id=1)

    async def ensure_dataset_exists(self, *args, **kwargs) -> None:
        return None

    async def get_dataset_id(self, *args, **kwargs) -> str | None:
        return "dataset-id"

    def resolve_dataset_alias(self, alias: str) -> str:
        return alias

    def get_registered_identifier(self, canonical: str) -> str:
        return canonical

    async def get_counts(self, *args, **kwargs) -> dict[str, int]:
        return {}

    def dump_identifier_map(self) -> dict[str, str]:
        return {}

    def _normalize_text(self, text: str) -> str:
        return str(text or "").strip()


class _ProjectionService:
    def __init__(self):
        self._kb = None
        self._waiter = None

    def attach_knowledge_base(self, kb) -> None:
        self._kb = kb

    def set_waiter(self, waiter) -> None:
        self._waiter = waiter

    async def probe(self, *args, **kwargs):
        return True, "ready"

    async def wait(self, *args, **kwargs):
        return ProjectionStatus.READY


class _GDriveLoader:
    def __init__(self, kb):
        self.kb = kb

    async def load(self):
        return None


class _SearchServiceStub:
    def __init__(self, kb_owner: "_KB | type[_KB] | None" = None):
        if isinstance(kb_owner, type):
            self._kb_instance = None
            self._kb_cls = kb_owner
        else:
            self._kb_instance = kb_owner
            self._kb_cls = type(kb_owner) if kb_owner is not None else _KB

    async def search(
        self,
        query: str,
        profile_id: int,
        k: int | None = None,
        *,
        datasets: Sequence[str] | None = None,
        user: Any | None = None,
        request_id: str | None = None,
    ) -> list[str]:
        kb_cls = self._kb_cls or _KB
        aliases = [kb_cls._resolve_dataset_alias(item) for item in list(datasets or [])]
        if not aliases:
            aliases = [kb_cls.GLOBAL_DATASET]
        results: list[str] = []
        lowered = str(query or "").strip().lower()
        for alias in aliases:
            for row in kb_cls._DATASETS.get(alias, []):
                text_value = row.text
                if not lowered or lowered in text_value.lower():
                    results.append(text_value)
                    if k is not None and len(results) >= k:
                        return results
        cognee_mod = getattr(kb_module, "cognee", None)
        search_impl = getattr(cognee_mod, "search", None) if cognee_mod else None
        if callable(search_impl):
            payload = await search_impl(query, datasets=aliases, user=user, top_k=k)
            if isinstance(payload, list):
                results.extend(payload)
        return results

    async def _fallback_dataset_entries(
        self,
        datasets: Sequence[str],
        user_ctx: Any | None,
        top_k: int = 6,
    ) -> list[tuple[str, str]]:
        kb_cls = self._kb_cls or _KB
        kb_instance = self._kb_instance or kb_cls()
        dataset_service = getattr(kb_instance, "dataset_service", None)
        entries: list[tuple[str, str]] = []
        for dataset in datasets:
            rows = []
            if dataset_service is not None:
                list_fn = getattr(dataset_service.__class__, "list_dataset_entries", None)
                if callable(list_fn):
                    rows = await list_fn(dataset_service, dataset, user_ctx)
            if not rows:
                rows = await kb_cls._list_dataset_entries(dataset, user_ctx)
            for row in rows:
                prepared = kb_cls._prepare_dataset_row(row, dataset)
                metadata = prepared.metadata or {}
                if metadata.get("kind") == "message":
                    continue
                entries.append((prepared.text, dataset))
                if len(entries) >= top_k:
                    return entries
        return entries


gdrive_loader_module.GDriveDocumentLoader = _GDriveLoader
cognee_config._package_storage_candidates = lambda: []
cognee_config.CogneeConfig.apply = classmethod(lambda cls: None)


class BaseSettings:
    DEFAULTS = {
        "API_URL": "http://testserver",
        "API_KEY": "test-api-key",
        "REQUEST_TIMEOUT": 5,
        "RETRY_ATTEMPTS": 2,
        "AI_COACH_REQUEST_TIMEOUT": 30,
        "AI_COACH_PROJECTION_TIMEOUT": 10,
        "AI_COACH_MAX_TOOL_CALLS": 3,
        "COGNEE_GLOBAL_DATASET": "global-dataset",
        "COGNEE_STORAGE_ROOT": "/tmp/cognee",
        "COGNEE_STORAGE_PATH": ".cognee_test_storage",
        "BOT_TOKEN": "test_token",
        "GOOGLE_APPLICATION_CREDENTIALS": "{}",
        "SPREADSHEET_ID": "test_spreadsheet_id",
        "AGENT_PROVIDER": "openai",
        "LLM_API_KEY": "test-key",
    }

    def __init__(self, **values):
        data = {**_PROD_DEFAULTS.model_dump(), **self.DEFAULTS, **values}
        for k, v in data.items():
            setattr(self, k, v)


settings_stub = BaseSettings()
app_settings.settings = settings_stub


class _ContainerStub:
    def __getattr__(self, name: str):
        if name.endswith("_service"):
            service = types.SimpleNamespace()
            if name == "ai_coach_service":

                async def create_workout_plan(*args: Any, **kwargs: Any) -> Any:
                    return types.SimpleNamespace(id=1)

                async def update_workout_plan(*args: Any, **kwargs: Any) -> Any:
                    return types.SimpleNamespace(id=1)

                service.create_workout_plan = create_workout_plan
                service.update_workout_plan = update_workout_plan
            return lambda: service
        raise AttributeError(name)


APIService.configure(lambda: _ContainerStub())


async def _dummy_get_user() -> types.SimpleNamespace:
    return types.SimpleNamespace(id=1)


if not hasattr(kb_module, "get_default_user"):
    kb_module.get_default_user = _dummy_get_user


async def _dummy_safe_add(*args: Any, **kwargs: Any) -> types.SimpleNamespace:
    return types.SimpleNamespace(dataset_id=kwargs.get("dataset_name"))


if not hasattr(kb_module, "_safe_add"):
    kb_module._safe_add = _dummy_safe_add


# Basic replacement for pytest-mock's `mocker` fixture so tests can patch objects without adding a dependency.
class _SimpleMocker:
    def __init__(self) -> None:
        self._patchers: list[object] = []

    def patch(self, target: str, *args: Any, **kwargs: Any) -> object:
        patcher = _patch(target, *args, **kwargs)
        self._patchers.append(patcher)
        return patcher.start()

    def patch_object(self, target: type[Any], attribute: str, *args: Any, **kwargs: Any) -> object:
        patcher = _patch.object(target, attribute, *args, **kwargs)
        self._patchers.append(patcher)
        return patcher.start()

    def stopall(self) -> None:
        while self._patchers:
            patcher = self._patchers.pop()
            patcher.stop()


@pytest.fixture(name="mocker")
def _mocker_fixture() -> _SimpleMocker:
    context = _SimpleMocker()
    try:
        yield context
    finally:
        context.stopall()


# KnowledgeBase stub


class _KB:
    GLOBAL_DATASET = "kb_global"
    HashStore = kb_module.HashStore
    _storage_dir = Path(settings_stub.COGNEE_STORAGE_PATH)
    _DATASETS: defaultdict[str, list[DatasetRow]] = defaultdict(list)
    _DATASET_IDS: dict[str, str] = {}
    _DATASET_ALIASES: dict[str, str] = {}
    _PROJECTED_DATASETS: set[str] = set()
    _PROJECTION_STATE: dict[str, tuple[ProjectionStatus, str]] = {}
    _LAST_REBUILD_RESULT: dict[str, dict[str, Any]] = {}
    _user: Any | None = None
    _list_data_supports_user: bool | None = None
    _list_data_requires_user: bool | None = None

    def __init__(self):
        self.dataset_service = _DatasetService()
        self.projection_service = _ProjectionService()
        self.projection_service.attach_knowledge_base(self)
        self.storage_service = types.SimpleNamespace(attach_knowledge_base=lambda *a, **k: None)
        self.chat_queue_service = types.SimpleNamespace()
        self.search_service = _SearchServiceStub(self)
        self._seen: set[tuple[int]] = set()

    @classmethod
    def _record_projection(cls, alias: str, status: ProjectionStatus, reason: str) -> None:
        if alias.startswith("kb_"):
            cls._PROJECTED_DATASETS.add(alias)
            cls._PROJECTION_STATE[alias] = (status, reason)

    async def initialize(self, knowledge_loader=None):
        user = await self.dataset_service.get_cognee_user()
        type(self)._user = user
        if knowledge_loader is not None:
            load = getattr(knowledge_loader, "load", None)
            if load is not None:
                result = load()
                if hasattr(result, "__await__"):
                    await result

    async def get_message_history(self, profile_id: int, *a, **k):
        key = (profile_id,)
        if key in self._seen:
            return []
        self._seen.add(key)
        kb_cls = type(self)
        rows = kb_cls._DATASETS.get(kb_cls._dataset_name(profile_id), [])
        if not rows:
            return ["msg1", "msg2"]
        raw_limit = int(k.get("limit", 2)) if k else 2
        limit = max(1, raw_limit)
        return [row.text for row in rows][-limit:]

    @classmethod
    async def search(
        cls, query: str, profile_id: int, k: int | None = None, *, request_id: str | None = None
    ) -> list[str]:
        alias = cls._resolve_dataset_alias(cls._dataset_name(profile_id))
        actor = await cls._get_cognee_user()
        await cls._ensure_profile_indexed(profile_id, actor)
        await cls._ensure_dataset_exists(alias, actor)
        datasets = [alias]
        try:
            global_status = await cls.ensure_global_projected(timeout=2.0)
        except Exception:
            global_status = ProjectionStatus.TIMEOUT
        if global_status == ProjectionStatus.READY:
            datasets.append(cls.GLOBAL_DATASET)
        try:
            return await cls._search_single_query(query, datasets, actor, k, profile_id, request_id=request_id)
        except Exception:
            fallback_alias = cls._resolve_dataset_alias(cls.GLOBAL_DATASET)
            return await cls._search_single_query(
                query,
                [fallback_alias],
                actor,
                k,
                profile_id,
                request_id=request_id,
            )

    @classmethod
    async def add_text(
        cls,
        text: str,
        *,
        dataset: str | None = None,
        node_set: list[str] | None = None,
        profile_id: int | None = None,
        role: Any | None = None,
        metadata: Mapping[str, Any] | None = None,
        project: bool = True,
    ) -> tuple[str, bool]:
        target = dataset or (cls._dataset_name(profile_id) if profile_id is not None else cls.GLOBAL_DATASET)
        role_value = getattr(role, "value", role)
        text_value = text if role_value is None else f"{role_value}: {text}"
        meta_payload = dict(metadata or {})
        meta_payload.setdefault("dataset", cls._resolve_dataset_alias(target))
        if role_value:
            meta_payload.setdefault("kind", "message")
            meta_payload.setdefault("role", role_value)
        else:
            meta_payload.setdefault("kind", "document")
        actor = await cls._get_cognee_user()
        if actor is None:
            actor = cls._user
        attempts = 0
        while attempts < 2:
            try:
                alias, created = await cls.update_dataset(
                    text_value,
                    target,
                    actor,
                    node_set=node_set or [],
                    metadata=meta_payload,
                )
            except FileNotFoundError:
                attempts += 1
                digest_md5 = md5(text_value.encode("utf-8")).hexdigest()
                cls._ensure_storage_file(digest_md5, text_value, dataset=target)
                clear_fn = getattr(kb_module.HashStore, "clear", None)
                if callable(clear_fn):
                    await clear_fn(target)
                await cls.rebuild_dataset(target, actor)
                continue
            if created and project:
                await cls._process_dataset(alias, actor)
            break
        return None

    @classmethod
    async def fallback_entries(cls, profile_id: int, limit: int = 6) -> list[tuple[str, str]]:
        instance = cls()
        datasets = [cls._resolve_dataset_alias(cls._dataset_name(profile_id)), cls.GLOBAL_DATASET]
        return await instance.search_service._fallback_dataset_entries(datasets, user_ctx=cls._user, top_k=limit)

    @classmethod
    async def update_dataset(
        cls,
        text: str,
        dataset: str,
        user: Any | None = None,
        node_set: list[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[str, bool]:
        alias = cls._resolve_dataset_alias(dataset)
        normalized = cls._normalize_text(text)
        if not normalized:
            return alias, False
        actor = user or cls._user or types.SimpleNamespace(id=1)
        await cls._ensure_dataset_exists(alias, actor)
        digest_sha = cls._compute_digests(normalized)
        digest_md5 = md5(normalized.encode("utf-8")).hexdigest()
        meta_payload = dict(metadata or {})
        meta_payload.setdefault("dataset", alias)
        meta_payload.setdefault("digest_sha", digest_sha)
        meta_payload.setdefault("digest_md5", digest_md5)
        cls._ensure_storage_file(digest_md5, normalized, dataset=alias)
        duplicate = False
        contains = getattr(cls.HashStore, "contains", None)
        if callable(contains):
            duplicate = await contains(alias, digest_sha)
        add_fn = getattr(cls.HashStore, "add", None)
        if callable(add_fn):
            await add_fn(alias, digest_sha, metadata=meta_payload)
        storage_row = DatasetRow(text=normalized, metadata=dict(meta_payload))
        if not duplicate:
            cls._DATASETS[alias].append(storage_row)
        safe_add = getattr(kb_module, "_safe_add", None)
        if callable(safe_add):
            await safe_add(normalized, dataset_name=alias, user=actor, node_set=list(node_set or []))
        return alias, not duplicate

    @classmethod
    async def save_client_message(cls, text: str, profile_id: int, *, language: str | None = None) -> None:
        await cls.add_text(
            text,
            dataset=cls.chat_dataset_name(profile_id),
            profile_id=profile_id,
            role=types.SimpleNamespace(value="client"),
            project=False,
        )

    @classmethod
    async def save_ai_message(cls, text: str, profile_id: int, *, language: str | None = None) -> None:
        await cls.add_text(
            text,
            dataset=cls.chat_dataset_name(profile_id),
            profile_id=profile_id,
            role=types.SimpleNamespace(value="ai"),
            project=False,
        )

    @staticmethod
    def _normalize_text(text: str | None) -> str:
        return str(text or "").strip()

    @classmethod
    def _dataset_name(cls, profile_id: int) -> str:
        return f"kb_profile_{profile_id}"

    @classmethod
    def chat_dataset_name(cls, profile_id: int) -> str:
        return f"chat_{profile_id}"

    @classmethod
    def _resolve_dataset_alias(cls, alias: str) -> str:
        value = str(alias or "")
        if value.startswith("client_"):
            suffix = value[len("client_") :]
            if suffix.isdigit():
                return f"kb_profile_{suffix}"
            return value
        if value.startswith("kb_"):
            return value
        if value.isdigit():
            return f"kb_profile_{value}"
        return value

    @classmethod
    def _alias_for_dataset(cls, alias: str) -> str:
        return cls._resolve_dataset_alias(alias)

    @classmethod
    async def _ensure_dataset_exists(cls, name: str, user: Any | None) -> str:
        alias = cls._alias_for_dataset(name)
        cls._DATASETS.setdefault(alias, [])
        if alias not in cls._DATASET_IDS:
            dataset_id = str(uuid4())
            cls._DATASET_IDS[alias] = dataset_id
            cls._DATASET_ALIASES[dataset_id] = alias
        return alias

    @classmethod
    def _storage_root(cls) -> Path:
        cls._storage_dir.mkdir(parents=True, exist_ok=True)
        return cls._storage_dir

    @classmethod
    def _ensure_storage_file(cls, digest_md5: str, text: str, *, dataset: str | None = None):
        root = cls._storage_root()
        path = root / f"text_{digest_md5}.txt"
        path.write_text(text, encoding="utf-8")
        return path, True

    @classmethod
    async def _list_dataset_entries(cls, dataset: str, user: Any | None):
        alias = cls._alias_for_dataset(dataset)
        return list(cls._DATASETS.get(alias, []))

    @classmethod
    async def _ensure_profile_indexed(cls, profile_id: int, user: Any | None) -> bool:
        api_service = getattr(kb_module, "APIService", APIService)
        profile_service = getattr(api_service, "profile", None)
        get_profile = getattr(profile_service, "get_profile", None) if profile_service else None
        if not callable(get_profile):
            return False
        try:
            profile_data = await get_profile(profile_id)
        except Exception:
            return False
        if profile_data is None:
            return False
        parts = [f"id: {getattr(profile_data, 'id', profile_id)}"]
        for field in ("profile", "gender", "workout_goals", "weight"):
            value = getattr(profile_data, field, None)
            if value:
                parts.append(f"{field}: {value}")
        text = "profile: " + "; ".join(parts)
        metadata = {"kind": "document", "source": "profile"}
        dataset = cls._dataset_name(profile_id)
        node_set = ["profile", f"profile:{profile_id}"]
        alias, created = await cls.update_dataset(text, dataset, user, node_set=node_set, metadata=metadata)
        if created:
            await cls._process_dataset(alias, user)
        return bool(created)

    @classmethod
    async def _collect_metadata(cls, digest: str, datasets: Sequence[str]):
        for dataset in datasets:
            alias = cls._alias_for_dataset(dataset)
            for row in cls._DATASETS.get(alias, []):
                metadata = row.metadata or {}
                if metadata.get("digest_sha") == digest or metadata.get("digest_md5") == digest:
                    return alias, dict(metadata)
        return None, None

    @classmethod
    def _prepare_dataset_row(cls, row: DatasetRow | Any, dataset: str) -> DatasetRow:
        metadata = dict(getattr(row, "metadata", {}) or {})
        text = getattr(row, "text", "") or ""
        normalized = cls._normalize_text(text)
        digest_md5 = metadata.get("digest_md5")
        if not normalized and digest_md5:
            path = cls._storage_root() / f"text_{digest_md5}.txt"
            if path.exists():
                normalized = cls._normalize_text(path.read_text(encoding="utf-8"))
        if not digest_md5:
            digest_md5 = md5(normalized.encode("utf-8")).hexdigest()
        metadata.setdefault("digest_md5", digest_md5)
        metadata.setdefault("digest_sha", cls._compute_digests(normalized))
        metadata.setdefault("dataset", dataset)
        return DatasetRow(text=normalized, metadata=metadata)

    @classmethod
    async def _build_snippets(
        cls, entries: Sequence[Any], datasets: Sequence[str], user: Any | None
    ) -> list[KnowledgeSnippet]:
        snippets: list[KnowledgeSnippet] = []
        dataset_list = list(datasets) or [cls.GLOBAL_DATASET]
        for entry in entries:
            metadata: dict[str, Any] = {}
            dataset_name: str | None = None
            if isinstance(entry, Mapping):
                metadata = dict(entry.get("metadata") or {})
                text_value = cls._normalize_text(str(entry.get("text", "")))
                dataset_name = metadata.get("dataset") or entry.get("dataset") or entry.get("dataset_name")
            else:
                metadata = dict(getattr(entry, "metadata", {}) or {})
                text_value = cls._normalize_text(str(getattr(entry, "text", entry)))
                dataset_name = (
                    metadata.get("dataset") or getattr(entry, "dataset_name", None) or getattr(entry, "dataset", None)
                )
            if not text_value:
                continue
            digest_sha = metadata.get("digest_sha") or cls._compute_digests(text_value)
            metadata_available = bool(metadata) or bool(dataset_name)
            if not metadata_available:
                dataset_name, metadata = await cls._collect_metadata(digest_sha, dataset_list)
                metadata = metadata or {}
            if not dataset_name:
                dataset_name = dataset_list[0]
            kind = metadata.get("kind", "document")
            if kind == "message":
                continue
            snippet = KnowledgeSnippet(text=text_value, dataset=dataset_name, kind=kind)
            snippets.append(snippet)
            add_fn = getattr(cls.HashStore, "add", None)
            if callable(add_fn):
                await add_fn(dataset_name, digest_sha, metadata=metadata)
        return snippets

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
        rows = list(entries) if entries is not None else await cls._list_dataset_entries(alias, user)
        created = 0
        linked = 0
        for row in rows:
            prepared = cls._prepare_dataset_row(row, alias)
            metadata = dict(prepared.metadata or {})
            digest_sha = metadata.get("digest_sha") or cls._compute_digests(prepared.text)
            digest_md5 = metadata.get("digest_md5") or digest_sha
            storage_root = cls._storage_root()
            if reason == "md5_promotion":
                target_digest = digest_sha
            else:
                target_digest = digest_md5
            target_path = storage_root / f"text_{target_digest}.txt"
            target_path.write_text(prepared.text, encoding="utf-8")
            if reason == "md5_promotion" and digest_md5 and digest_md5 != digest_sha:
                legacy_path = storage_root / f"text_{digest_md5}.txt"
                if legacy_path.exists():
                    legacy_path.unlink()
            add_fn = getattr(cls.HashStore, "add", None)
            if callable(add_fn):
                await add_fn(alias, digest_sha, metadata=metadata)
            created += 1
            linked += 1
        return created, linked

    @classmethod
    async def _rebuild_from_disk(cls, dataset: str) -> tuple[int, int]:
        alias = cls._alias_for_dataset(dataset)
        root = cls._storage_root()
        created = 0
        linked = 0
        for path in root.glob("text_*.txt"):
            raw = path.read_text(encoding="utf-8")
            normalized = cls._normalize_text(raw)
            digest_md5 = path.stem.replace("text_", "")
            digest_sha = cls._compute_digests(normalized)
            metadata = {"dataset": alias, "digest_md5": digest_md5, "digest_sha": digest_sha}
            add_fn = getattr(cls.HashStore, "add", None)
            if callable(add_fn):
                await add_fn(alias, digest_sha, metadata=metadata)
            created += 1
            linked += 1
        return created, linked

    @classmethod
    async def _get_dataset_metadata(cls, dataset: str, user: Any | None = None) -> dict[str, Any]:
        alias = cls._alias_for_dataset(dataset)
        rows = cls._DATASETS.get(alias, [])
        return {"dataset": alias, "documents": len(rows)}

    @classmethod
    async def _get_dataset_id(cls, dataset: str, user: Any | None) -> str:
        alias = cls._alias_for_dataset(dataset)
        return cls._DATASET_IDS.get(alias, alias)

    @classmethod
    def _to_user_ctx(cls, user: Any | None) -> Any | None:
        return user

    @classmethod
    async def _fetch_dataset_rows(
        cls, list_data: Callable[..., Awaitable[Iterable[Any]]], dataset: str, user: Any | None
    ) -> list[Any]:
        dataset_id = cls._DATASET_IDS.get(dataset, dataset)
        supports_flag = cls._list_data_supports_user
        requires_flag = cls._list_data_requires_user
        supports_user = True if supports_flag is None else bool(supports_flag)
        requires_user = False if requires_flag is None else bool(requires_flag)
        needs_user_arg = supports_user or requires_user
        args = [dataset_id]
        if needs_user_arg and user is not None:
            args.append(user)
        result = await list_data(*args)
        return list(result or [])

    @classmethod
    def get_projection_health(cls, alias: str) -> dict[str, str]:
        resolved = cls._alias_for_dataset(alias)
        status = cls._PROJECTION_STATE.get(resolved, (ProjectionStatus.READY, "ready"))
        return {"dataset": resolved, "status": status[0].value}

    @classmethod
    def get_last_rebuild_result(cls) -> dict[str, dict[str, Any]]:
        return cls._LAST_REBUILD_RESULT

    @classmethod
    def _compute_digests(cls, text: str) -> str:
        normalized = cls._normalize_text(text)
        return sha256(normalized.encode("utf-8")).hexdigest()

    @classmethod
    async def rebuild_dataset(cls, dataset: str, user: Any | None, sha_only: bool = False):
        alias = cls._alias_for_dataset(dataset)
        entries = await cls._list_dataset_entries(alias, user)
        reinserted = 0
        if entries:
            for entry in entries:
                await cls.update_dataset(entry.text, alias, user, metadata=entry.metadata)
                reinserted += 1
        else:
            created, linked = await cls._rebuild_from_disk(alias)
            reinserted += created
            cls._LAST_REBUILD_RESULT[alias] = {"linked": linked, "documents": created, "sha_only": sha_only}
            return types.SimpleNamespace(
                reinserted=reinserted,
                healed_documents=0,
                linked=linked,
                rehydrated=0,
                last_dataset=alias,
                healed=True,
                reason="ok",
            )
        cls._LAST_REBUILD_RESULT[alias] = {"documents": reinserted, "healed": 0, "sha_only": sha_only}
        return types.SimpleNamespace(
            reinserted=reinserted,
            healed_documents=0,
            linked=0,
            rehydrated=0,
            last_dataset=alias,
            healed=True,
            reason="ok",
        )

    @classmethod
    async def _project_dataset(cls, dataset: str, user: Any | None):
        alias = cls._alias_for_dataset(dataset)
        cognify = getattr(getattr(kb_module, "cognee", None), "cognify", None)
        if callable(cognify):
            try:
                await cognify(datasets=[alias], user=user)
            except FileNotFoundError:
                entries = await cls._list_dataset_entries(alias, user)
                await cls._heal_dataset_storage(alias, user, entries=entries, reason="storage_missing")
                await cognify(datasets=[alias], user=user)
        cls._record_projection(alias, ProjectionStatus.READY, "ready")
        return ProjectionStatus.READY

    @classmethod
    async def _process_dataset(cls, dataset: str, user: Any | None = None) -> None:
        if user is None:
            user = cls._user
        await cls._project_dataset(dataset, user)

    @classmethod
    async def _ensure_dataset_projected(cls, dataset: str, user: Any | None, timeout: float | None = None) -> bool:
        await cls._project_dataset(dataset, user)
        return True

    @classmethod
    async def _get_cognee_user(cls):
        return cls._user

    @classmethod
    async def ensure_global_projected(cls, timeout: float | None = None):
        alias = cls._alias_for_dataset(cls.GLOBAL_DATASET)
        user = await cls._get_cognee_user()
        status = await cls._wait_for_projection(alias, user, timeout_s=timeout)
        if status is ProjectionStatus.TIMEOUT:
            entries = await cls._list_dataset_entries(alias, user)
            await cls._heal_dataset_storage(alias, user, entries=entries, reason="global_retry")
            status = await cls._wait_for_projection(alias, user, timeout_s=timeout)
        if status is ProjectionStatus.READY:
            cls._record_projection(alias, status, "ready")
        return status

    @classmethod
    async def _wait_for_projection(cls, dataset: str, user: Any | None, timeout_s: float | None = None):
        actor = user or await cls._get_cognee_user()
        if actor is None:
            return ProjectionStatus.TIMEOUT
        alias = cls._alias_for_dataset(dataset)
        ready, reason = await cls._is_projection_ready(dataset, actor)
        if ready:
            cls._record_projection(alias, ProjectionStatus.READY, reason)
            return ProjectionStatus.READY
        if timeout_s is not None and timeout_s > 0:
            await asyncio.sleep(min(timeout_s, 0.01))
            ready, reason = await cls._is_projection_ready(dataset, actor)
            if ready:
                cls._record_projection(alias, ProjectionStatus.READY, reason)
                return ProjectionStatus.READY
        return ProjectionStatus.TIMEOUT

    @classmethod
    async def _is_projection_ready(cls, dataset: str, user: Any | None) -> tuple[bool, str]:
        alias = cls._alias_for_dataset(dataset)
        # if alias == cls.GLOBAL_DATASET:
        #     return True, "ready"
        if alias in cls._PROJECTED_DATASETS:
            return True, "ready"
        rows = await cls._list_dataset_entries(alias, user)
        if not rows:
            datasets_api = getattr(getattr(kb_module, "cognee", types.SimpleNamespace()), "datasets", None)
            list_data_fn = getattr(datasets_api, "list_data", None) if datasets_api else None
            fetcher = getattr(cls, "_fetch_dataset_rows", None)
            if callable(fetcher) and callable(list_data_fn):
                rows = await fetcher(list_data_fn, alias, user)
        if not rows:
            return False, "pending"
        non_content = True
        for row in rows:
            prepared = cls._prepare_dataset_row(row, alias)
            metadata = prepared.metadata or {}
            if metadata.get("kind") != "message":
                non_content = False
            digest_sha = metadata.get("digest_sha")
            if digest_sha:
                add_fn = getattr(cls.HashStore, "add", None)
                if callable(add_fn):
                    await add_fn(alias, digest_sha, metadata=metadata)
        if non_content:
            return True, "all_rows_empty_content"
        return True, "ready"

    @classmethod
    async def refresh(cls) -> None:
        await cls._ensure_dataset_exists(cls.GLOBAL_DATASET, cls._user)
        cls._record_projection(cls.GLOBAL_DATASET, ProjectionStatus.READY, "refresh")

    @classmethod
    async def debug_snapshot(cls, profile_id: int | None = None) -> dict[str, Any]:
        user = await cls._get_cognee_user()
        datasets: list[str] = []
        if profile_id is not None:
            datasets.append(cls._dataset_name(profile_id))
        datasets.append(cls.GLOBAL_DATASET)
        snapshot: list[dict[str, Any]] = []
        for dataset in datasets:
            entries = await cls._list_dataset_entries(dataset, user)
            metadata = await cls._get_dataset_metadata(dataset, user)
            ready, reason = await cls._is_projection_ready(dataset, user)
            meta_payload: dict[str, Any] = {}
            if isinstance(metadata, Mapping):
                meta_payload = dict(metadata)
            elif hasattr(metadata, "__dict__"):
                meta_payload = dict(metadata.__dict__)
            item_id = str(meta_payload.get("id", dataset))
            snapshot.append(
                {
                    "alias": dataset,
                    "documents": len(entries),
                    "metadata": meta_payload,
                    "id": item_id,
                    "projection": {"ready": ready, "reason": reason},
                }
            )
        return {"datasets": snapshot}

    @classmethod
    async def _search_single_query(
        cls,
        query: str,
        datasets: list[str],
        user: Any | None,
        k: int | None,
        profile_id: int,
        *,
        request_id: str | None = None,
    ):
        instance = cls()
        return await instance.search_service.search(
            query, profile_id, k, datasets=datasets, user=user, request_id=request_id
        )


kb_module.KnowledgeBase = _KB

import ai_coach.agent as agent_module  # noqa: E402
from ai_coach.agent.coach import CoachAgent as _CoachAgent, QAResponse as _QAResponse  # noqa: E402
from ai_coach.agent.utils import ProgramAdapter as _ProgramAdapter  # noqa: E402
import ai_coach.api as api_module  # noqa: E402


async def _dummy_agent_run(*args, **kwargs):
    return {"output": {"answer": "ok"}}


_CoachAgent._get_agent = staticmethod(lambda *a, **k: types.SimpleNamespace(run=_dummy_agent_run))
_CoachAgent._run_completion = staticmethod(lambda *a, **k: {"choices": [{"message": {"content": "ok"}}]})
_CoachAgent._get_completion_client = staticmethod(lambda *a, **k: object())

import ai_coach.api  # noqa: E402,F401

agent_module.CoachAgent = _CoachAgent
agent_module.QAResponse = _QAResponse
agent_module.ProgramAdapter = _ProgramAdapter
api_module.CoachAgent = _CoachAgent
api_module.ProgramAdapter = _ProgramAdapter
api_module.KnowledgeBase = _KB
import ai_coach.agent.tools as agent_tools_module  # noqa: E402

agent_tools_module.KnowledgeBase = _KB
if not hasattr(kb_module, "cognee"):
    kb_module.cognee = types.SimpleNamespace()


async def _dummy_cognee_search(*args: Any, **kwargs: Any) -> list[Any]:
    return []


async def _dummy_cognee_void(*args: Any, **kwargs: Any) -> None:
    return None


if not hasattr(kb_module.cognee, "search"):
    kb_module.cognee.search = _dummy_cognee_search
if not hasattr(kb_module.cognee, "init_knowledge_base"):
    kb_module.cognee.init_knowledge_base = _dummy_cognee_void
if not hasattr(kb_module.cognee, "reinit"):
    kb_module.cognee.reinit = _dummy_cognee_void
if not hasattr(kb_module.cognee, "cognify"):
    kb_module.cognee.cognify = _dummy_cognee_void
