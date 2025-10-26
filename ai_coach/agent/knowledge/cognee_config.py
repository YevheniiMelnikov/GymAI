import importlib
import os
from importlib import import_module

# pyrefly: ignore-file
# ruff: noqa
"""Cognee configuration helpers."""

from pathlib import Path
from types import ModuleType
from typing import Any, Awaitable, Callable, ClassVar, Optional, cast
from uuid import uuid4

import cognee
from loguru import logger
from sqlalchemy import schema as sa_schema

from config.app_settings import settings


def _directory_snapshot(path: Path, limit: int = 10) -> tuple[list[str], int]:
    try:
        entries: list[str] = []
        count = 0
        for item in path.iterdir():
            count += 1
            if len(entries) < limit:
                entries.append(item.name)
        return entries, count
    except FileNotFoundError:
        return [], 0
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"cognee_storage_snapshot_failed path={path} detail={exc}")
        return [], 0


def _prepare_storage_root() -> Path:
    storage_candidate = (
        os.environ.get("COGNEE_STORAGE_PATH") or os.environ.get("COGNEE_DATA_ROOT") or settings.COGNEE_STORAGE_PATH
    )
    root = Path(storage_candidate).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for sub in (".cognee_system/databases", ".cognee_system/vectordb"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    os.environ["COGNEE_STORAGE_PATH"] = str(root)
    os.environ["COGNEE_DATA_ROOT"] = str(root)
    _log_storage_details(root)
    return root


def _package_storage_candidates() -> list[Path]:
    base_dir = Path(cognee.__file__).resolve().parent
    names = ("cognee_storage", ".data_storage")
    candidates: list[Path] = []
    seen: set[str] = set()
    for name in names:
        candidate = base_dir / name
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def _collect_storage_info(root: Path | None) -> dict[str, Any]:
    package_candidates = _package_storage_candidates()
    package_storage = package_candidates[0] if package_candidates else Path(cognee.__file__).resolve().parent
    package_exists = False
    package_is_symlink = False
    package_target: str | None = None
    for candidate in package_candidates:
        exists = False
        is_symlink = False
        try:
            exists = candidate.exists()
            is_symlink = candidate.is_symlink()
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"cognee_storage_stat_failed path={candidate} detail={exc}")
        if exists or is_symlink:
            package_storage = candidate
            package_exists = exists or is_symlink
            package_is_symlink = is_symlink
            try:
                package_target = str(candidate.resolve(strict=False))
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"cognee_storage_readlink_failed path={candidate} detail={exc}")
            break
    if package_target is None:
        try:
            package_target = str(package_storage.resolve(strict=False))
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"cognee_storage_resolve_failed path={package_storage} detail={exc}")

    entries_sample: list[str]
    entries_count: int
    if root is not None and root.exists():
        entries_sample, entries_count = _directory_snapshot(root)
    else:
        entries_sample, entries_count = [], 0

    root_exists = root.exists() if isinstance(root, Path) else False
    root_writable = os.access(root, os.W_OK) if isinstance(root, Path) else False

    return {
        "root": str(root) if isinstance(root, Path) else None,
        "root_exists": root_exists,
        "root_writable": root_writable,
        "entries_sample": entries_sample,
        "entries_count": entries_count,
        "package_path": str(package_storage),
        "package_exists": package_exists,
        "package_is_symlink": package_is_symlink,
        "package_target": package_target,
        "package_candidates": [str(candidate) for candidate in package_candidates],
    }


def _log_storage_details(root: Path) -> None:
    info = _collect_storage_info(root)
    logger.info(
        f"cognee_storage prepared path={info['root']} exists={info['root_exists']} "
        f"writable={info['root_writable']} entries={info['entries_count']} sample={info['entries_sample']} "
        f"package_path={info['package_path']} package_exists={info['package_exists']} "
        f"package_is_symlink={info['package_is_symlink']} package_target={info['package_target']}"
    )


def _resolve_localfilestorage_class() -> Optional[type[Any]]:
    module_candidates = (
        "cognee.infrastructure.files.storage.LocalFileStorage",
        "cognee.infrastructure.files.storage.local_file_storage",
        "cognee.infrastructure.files.storage",
    )
    for module_path in module_candidates:
        try:
            module = import_module(module_path)
        except Exception:
            continue
        if isinstance(module, ModuleType):
            candidate = getattr(module, "LocalFileStorage", None)
            if isinstance(candidate, type):
                return candidate
    return None


def _patch_local_file_storage(root: Path) -> None:
    local_storage_cls = _resolve_localfilestorage_class()
    if local_storage_cls is None:
        logger.warning("LocalFileStorage class not found in Cognee storage module")
        return

    if getattr(local_storage_cls, "_gymbot_storage_patched", False):
        return

    allow_package_storage = os.getenv("COGNEE_ALLOW_PACKAGE_STORAGE", "0") == "1"

    original_open = getattr(local_storage_cls, "open", None)
    storage_attr = getattr(local_storage_cls, "storage_path", None) or getattr(local_storage_cls, "STORAGE_PATH", None)

    if hasattr(local_storage_cls, "storage_path"):
        setattr(local_storage_cls, "storage_path", str(root))
    if hasattr(local_storage_cls, "STORAGE_PATH"):
        setattr(local_storage_cls, "STORAGE_PATH", str(root))

    package_roots: list[Path] = []
    for candidate in _package_storage_candidates():
        try:
            package_roots.append(candidate.resolve(strict=False))
        except Exception:  # noqa: BLE001
            package_roots.append(candidate)

    def _remap_path(raw_path: Path) -> Path:
        if raw_path.is_absolute():
            try:
                if raw_path.is_relative_to(root):
                    return raw_path
            except ValueError:
                pass
            for package_storage in package_roots:
                try:
                    if raw_path.is_relative_to(package_storage):
                        relative = raw_path.relative_to(package_storage)
                        return (root / relative).resolve()
                except ValueError:
                    continue
            return (root / raw_path.name).resolve()
        return (root / raw_path).resolve()

    if not callable(original_open):
        logger.info(
            f"cognee_storage localfilestorage_no_open class={local_storage_cls.__name__} storage_path={storage_attr}"
        )
        setattr(local_storage_cls, "_gymbot_storage_patched", True)
        return

    def open_with_project_storage(self: Any, file_path: str, mode: str = "r", **kwargs: Any) -> Any:
        raw_path = Path(file_path)
        target_path = _remap_path(raw_path)
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            target_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            return target_path.open(mode, **kwargs)
        except FileNotFoundError:
            if allow_package_storage and callable(original_open):
                logger.warning(f"cognee_storage package_fallback file={file_path} root={root}")
                return original_open(self, file_path, mode, **kwargs)
            raise

    setattr(local_storage_cls, "open", open_with_project_storage)
    setattr(local_storage_cls, "_gymbot_storage_patched", True)

    logger.info(
        f"cognee_storage patched_local_file_storage class={local_storage_cls.__name__} "
        f"root={root} storage_path={storage_attr} allow_package_storage={allow_package_storage}"
    )


class CogneeConfig:
    _STORAGE_ROOT: ClassVar[Path | None] = None

    @classmethod
    def apply(cls) -> None:
        storage_root = _prepare_storage_root()
        cls._STORAGE_ROOT = storage_root
        _patch_local_file_storage(storage_root)
        cls._configure_llm()
        cls._configure_vector_db()
        cls._configure_relational_db()
        cls._patch_cognee()
        cls._patch_dataset_creation()
        cls._patch_rbac_and_dataset_resolvers()

    @classmethod
    def storage_root(cls) -> Path | None:
        return cls._STORAGE_ROOT

    @classmethod
    def describe_storage(cls) -> dict[str, Any]:
        root = cls._STORAGE_ROOT
        if root is None:
            candidate = os.environ.get("COGNEE_STORAGE_PATH") or os.environ.get("COGNEE_DATA_ROOT")
            if candidate:
                root = Path(candidate).expanduser().resolve()
        return _collect_storage_info(root)

    @staticmethod
    def _configure_llm() -> None:
        cognee.config.set_llm_provider(settings.LLM_PROVIDER)
        cognee.config.set_llm_model(settings.LLM_MODEL)
        cognee.config.set_llm_api_key(settings.LLM_API_KEY)
        cognee.config.set_llm_endpoint(settings.LLM_API_URL)

    @staticmethod
    def _configure_vector_db() -> None:
        cognee.config.set_vector_db_provider(settings.VECTORDATABASE_PROVIDER)
        cognee.config.set_vector_db_url(settings.VECTORDATABASE_URL)

    @staticmethod
    def _configure_relational_db() -> None:
        cognee.config.set_relational_db_config(
            {
                "db_host": settings.DB_HOST,
                "db_port": settings.DB_PORT,
                "db_username": settings.DB_USER,
                "db_password": settings.DB_PASSWORD,
                "db_name": settings.DB_NAME,
                "db_path": "",
                "db_provider": settings.DB_PROVIDER,
            }
        )

    @staticmethod
    def _patch_cognee() -> None:
        """Apply runtime patches to Cognee (ledger, embeddings, API adapter)."""
        try:
            from cognee.infrastructure.databases.vector.embeddings import LiteLLMEmbeddingEngine
            from cognee.modules.data.models.graph_relationship_ledger import GraphRelationshipLedger

            GenericAPIAdapter = None
            for path in [
                "cognee.infrastructure.llm.generic_api.adapter",
                "cognee.infrastructure.llm.generic_llm_api.adapter",
            ]:
                try:
                    mod = importlib.import_module(path)
                    GenericAPIAdapter = getattr(mod, "GenericAPIAdapter", None)
                    if GenericAPIAdapter:
                        break
                except Exception:
                    continue

            CogneeConfig._patch_graph_relationship_ledger(GraphRelationshipLedger)
            CogneeConfig._patch_litellm_embedding_engine(LiteLLMEmbeddingEngine)  # pyrefly: ignore[bad-argument-type]
            if GenericAPIAdapter:
                CogneeConfig._patch_generic_api_adapter(GenericAPIAdapter)

        except Exception as e:
            logger.debug(f"Cognee patch failed: {e}")

    @staticmethod
    def _patch_graph_relationship_ledger(ledger_cls: type) -> None:
        """Fix default ID generation for graph relationship ledger."""
        ledger_cls.__table__.c.id.default = sa_schema.ColumnDefault(uuid4)  # noqa

    @staticmethod
    def _patch_litellm_embedding_engine(engine_cls: type) -> None:
        """Replace embedding method with LiteLLM-powered async function."""

        async def patched_embedding(texts: list[str], model: str | None = None, **kwargs: Any) -> Any:
            from litellm import embedding

            return await embedding(  # pyrefly: ignore[async-error]
                model=model or settings.EMBEDDING_MODEL,
                input=texts,
                api_key=settings.EMBEDDING_API_KEY,
                base_url=settings.EMBEDDING_ENDPOINT,
                dimensions=kwargs.get("dimensions"),
                user=kwargs.get("user"),
                extra_body=kwargs.get("extra_body"),
                metadata=kwargs.get("metadata"),
                caching=kwargs.get("caching", False),
            )

        engine_cls.embedding = staticmethod(patched_embedding)  # pyrefly: ignore[missing-attribute]

    @staticmethod
    def _patch_generic_api_adapter(adapter_cls: type) -> None:
        """Force GenericAPIAdapter to use OpenAI client."""
        original_create = getattr(adapter_cls, "create_client", None)

        async def _create_client(*args: Any, **kwargs: Any) -> Any:
            try:
                from openai import AsyncOpenAI

                return AsyncOpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_API_URL or None)
            except Exception:
                if callable(original_create):
                    result = original_create(*args, **kwargs)
                    if hasattr(result, "__await__"):
                        return await cast(Awaitable[Any], result)
                    return result
                raise

        setattr(adapter_cls, "create_client", staticmethod(_create_client))

    @classmethod
    def _patch_dataset_creation(cls) -> None:
        """Ensure create_authorized_dataset is properly loaded in Cognee."""
        try:
            m_lcd = importlib.import_module("cognee.modules.data.methods.load_or_create_datasets")
            cad_obj = m_lcd.__dict__.get("create_authorized_dataset")
            if not callable(cad_obj):
                m_cad = importlib.import_module("cognee.modules.data.methods.create_authorized_dataset")
                func = getattr(m_cad, "create_authorized_dataset", None)
                if callable(func):
                    m_lcd.__dict__["create_authorized_dataset"] = func
        except Exception as e:
            logger.debug(f"Patch dataset creation failed: {e}")

    @classmethod
    def _patch_rbac_and_dataset_resolvers(cls) -> None:
        """Harden RBAC and dataset resolvers to avoid errors on missing IDs."""
        try:
            m_all = importlib.import_module("cognee.modules.users.permissions.methods.get_all_user_permission_datasets")
            orig_all = getattr(m_all, "get_all_user_permission_datasets", None)
            m_auth = importlib.import_module("cognee.modules.data.methods.get_authorized_existing_datasets")
            orig_auth = getattr(m_auth, "get_authorized_existing_datasets", None)

            if callable(orig_all):
                original_all = cast(Callable[[Any, str], Awaitable[list[Any] | None]], orig_all)

                async def safe_all(user: Any, permission_type: str) -> list[Any]:
                    try:
                        res = await original_all(user, permission_type)
                    except Exception:
                        return []
                    return [x for x in (res or []) if getattr(x, "id", None)]

                setattr(m_all, "get_all_user_permission_datasets", safe_all)

            if callable(orig_auth):
                original_auth = cast(Callable[[list[Any], str, Any], Awaitable[list[Any] | None]], orig_auth)

                async def safe_auth(datasets: list[Any], permission_type: str, user: Any) -> list[Any]:
                    try:
                        res = await original_auth(datasets, permission_type, user)
                    except Exception:
                        return []
                    return [x for x in (res or []) if getattr(x, "id", None)]

                setattr(m_auth, "get_authorized_existing_datasets", safe_auth)

            for mod_path in [
                "cognee.modules.data.methods.get_authorized_existing_datasets",
                "cognee.modules.users.permissions.methods.get_specific_user_permission_datasets",
                "cognee.modules.pipelines.layers.resolve_authorized_user_datasets",
                "cognee.modules.data.methods.get_authorized_dataset_by_name",
                "cognee.modules.pipelines.layers.resolve_authorized_user_dataset",
            ]:
                mod = importlib.import_module(mod_path)
                if "get_all_user_permission_datasets" in mod.__dict__ and callable(orig_all):
                    mod.__dict__["get_all_user_permission_datasets"] = m_all.get_all_user_permission_datasets
                if "get_authorized_existing_datasets" in mod.__dict__ and callable(orig_auth):
                    mod.__dict__["get_authorized_existing_datasets"] = m_auth.get_authorized_existing_datasets
        except Exception as e:
            logger.debug(f"Patch RBAC resolvers failed: {e}")
