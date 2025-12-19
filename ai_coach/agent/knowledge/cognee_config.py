import importlib
import os
import cognee
from pathlib import Path
from textwrap import dedent
from types import ModuleType
from typing import Any, Awaitable, Callable, ClassVar, cast
from uuid import uuid4

from loguru import logger
from sqlalchemy import schema as sa_schema
from sqlalchemy.engine.url import URL, make_url

from ai_coach.agent.knowledge.utils.storage_helpers import (
    collect_storage_info,
    patch_local_file_storage,
    prepare_storage_root,
)
from config.app_settings import settings

_COGNEE_MODULE: ModuleType | None = None


class CogneeConfig:
    _STORAGE_ROOT: ClassVar[Path | None] = None

    @classmethod
    def apply(cls) -> None:
        storage_root = prepare_storage_root()
        cls._STORAGE_ROOT = storage_root

        global _COGNEE_MODULE
        if _COGNEE_MODULE is None:
            _COGNEE_MODULE = importlib.import_module("cognee")
        globals()["cognee"] = _COGNEE_MODULE

        cls._ensure_openai_env()

        patch_local_file_storage(storage_root)
        cls._configure_llm()
        cls._configure_vector_db()
        cls._configure_graph_db()
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
        return collect_storage_info(root)

    @staticmethod
    def _ensure_openai_env() -> None:
        openai_key = os.environ.get("OPENAI_API_KEY")
        if not openai_key and settings.LLM_API_KEY:
            os.environ["OPENAI_API_KEY"] = settings.LLM_API_KEY
            openai_key = settings.LLM_API_KEY

        openai_base = os.environ.get("OPENAI_BASE_URL")
        if not openai_base:
            candidate_url = settings.LLM_API_URL or settings.OPENAI_BASE_URL
            if candidate_url:
                os.environ["OPENAI_BASE_URL"] = candidate_url
                openai_base = candidate_url

        def _mask(value: str | None) -> str:
            if not value:
                return "unset"
            if len(value) <= 8:
                return value
            return f"{value[:4]}...{value[-4:]}"

        logger.debug(
            (
                "cognee_embedding_env OPENAI_BASE_URL={} LLM_PROVIDER={} "
                "AGENT_PROVIDER={} EMBEDDING_MODEL={} OPENAI_API_KEY={}"
            ),
            openai_base or "unset",
            settings.LLM_PROVIDER,
            settings.AGENT_PROVIDER,
            settings.EMBEDDING_MODEL,
            _mask(openai_key),
        )

    @staticmethod
    def _configure_llm() -> None:
        cognee.config.set_llm_provider(settings.LLM_PROVIDER)
        cognee.config.set_llm_model(settings.LLM_MODEL)
        cognee.config.set_llm_api_key(settings.LLM_API_KEY)
        cognee.config.set_llm_endpoint(settings.LLM_API_URL)

    @staticmethod
    def _configure_vector_db() -> None:
        provider = settings.VECTOR_DB_PROVIDER
        vector_url = settings.VECTOR_DB_URL
        vector_key = settings.VECTOR_DB_KEY
        vector_url_safe = CogneeConfig._render_safe_url(vector_url)
        vector_meta = CogneeConfig._extract_url_meta(vector_url)
        vector_host = vector_meta.get("host") or ""

        if provider == "qdrant":
            importlib.import_module("cognee_community_vector_adapter_qdrant.register")
            cognee.config.set_vector_db_config(
                {
                    "vector_db_provider": provider,
                    "vector_db_url": vector_url,
                    "vector_db_key": vector_key,
                }
            )
        else:
            cognee.config.set_vector_db_provider(provider)
            cognee.config.set_vector_db_url(vector_url)
        os.environ["VECTOR_DB_PROVIDER"] = provider
        os.environ["VECTOR_DB_URL"] = vector_url
        os.environ["VECTOR_DB_KEY"] = vector_key

        logger.info(
            "cognee_vector_config provider={} url={} host={} port={} db={} user={}",
            provider,
            vector_url_safe,
            vector_host or "unset",
            vector_meta.get("port") or "unset",
            vector_meta.get("database") or "unset",
            vector_meta.get("username") or "unset",
        )

    @staticmethod
    def _configure_graph_db() -> None:
        graph_host = settings.GRAPH_DATABASE_HOST or "neo4j"
        if graph_host in {"localhost", "127.0.0.1", ""}:
            graph_host = "neo4j"
        graph_port = settings.GRAPH_DATABASE_PORT or "7687"
        graph_url = settings.GRAPH_DATABASE_URL or f"bolt://{graph_host}:{graph_port}"

        env_graph_provider = os.environ.get("GRAPH_DATABASE_PROVIDER")
        if env_graph_provider and env_graph_provider != settings.GRAPH_DATABASE_PROVIDER:
            logger.warning(
                "cognee_graph_provider_mismatch env={} config={}",
                env_graph_provider,
                settings.GRAPH_DATABASE_PROVIDER,
            )
        os.environ["GRAPH_DATABASE_PROVIDER"] = settings.GRAPH_DATABASE_PROVIDER
        os.environ.setdefault("GRAPH_DATABASE_URL", graph_url)
        os.environ.setdefault("GRAPH_DATABASE_NAME", settings.GRAPH_DATABASE_NAME)
        os.environ.setdefault("GRAPH_DATABASE_USERNAME", settings.GRAPH_DATABASE_USERNAME)
        os.environ.setdefault("GRAPH_DATABASE_PASSWORD", settings.GRAPH_DATABASE_PASSWORD)
        os.environ.setdefault("GRAPH_DATABASE_PORT", str(graph_port))

        graph_db_config = {
            "graph_database_provider": settings.GRAPH_DATABASE_PROVIDER,
            "graph_database_url": graph_url,
            "graph_database_name": settings.GRAPH_DATABASE_NAME,
            "graph_database_username": settings.GRAPH_DATABASE_USERNAME,
            "graph_database_password": settings.GRAPH_DATABASE_PASSWORD,
            "graph_database_port": graph_port,
        }
        cognee.config.set_graph_db_config(graph_db_config)
        env_vector_provider = os.environ.get("VECTOR_DB_PROVIDER", "unset")
        logger.info(
            (
                "cognee_graph_config_applied env_graph_provider={} config_graph_provider={} "
                "env_vector_provider={} url={} host={} port={} name={} user={}"
            ),
            env_graph_provider or "unset",
            settings.GRAPH_DATABASE_PROVIDER,
            env_vector_provider,
            CogneeConfig._render_safe_url(graph_url),
            graph_host,
            graph_port,
            settings.GRAPH_DATABASE_NAME or "unset",
            settings.GRAPH_DATABASE_USERNAME or "unset",
        )

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

    @classmethod
    def _patch_cognee(cls) -> None:
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

            try:
                from cognee.infrastructure.databases.graph.neo4j_driver.adapter import Neo4jAdapter
            except Exception:  # noqa: BLE001
                Neo4jAdapter = None

            CogneeConfig._patch_graph_relationship_ledger(GraphRelationshipLedger)
            CogneeConfig._patch_litellm_embedding_engine(LiteLLMEmbeddingEngine)  # pyrefly: ignore[bad-argument-type]
            if Neo4jAdapter is not None:
                CogneeConfig._patch_neo4j_adapter(Neo4jAdapter)
            if GenericAPIAdapter:
                cls._patch_generic_api_adapter(GenericAPIAdapter)

        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Cognee patch failed: {exc}")

        cls._patch_graph_logging()
        cls._patch_add_data_points_logging()
        cls._patch_extract_graph_task()
        cls._patch_cognify_tasks()

    @staticmethod
    def _patch_graph_relationship_ledger(ledger_cls: type) -> None:
        """Fix default ID generation for graph relationship ledger."""
        ledger_cls.__table__.c.id.default = sa_schema.ColumnDefault(uuid4)  # noqa

    @staticmethod
    def _patch_litellm_embedding_engine(engine_cls: type) -> None:
        """Replace embedding method with LiteLLM-powered async function."""

        logger.trace(
            "Configuring LiteLLM embedding",
            model=settings.EMBEDDING_MODEL,
            endpoint=settings.EMBEDDING_ENDPOINT,
        )

        async def patched_embedding(texts: list[str], model: str | None = None, **kwargs: Any) -> Any:
            from litellm import embedding

            return await embedding(  # pyrefly: ignore[async-error]
                model=model or settings.EMBEDDING_MODEL,
                input=texts,
                api_key=settings.LLM_API_KEY,
                base_url=settings.EMBEDDING_ENDPOINT,
                dimensions=kwargs.get("dimensions"),
                user=kwargs.get("user"),
                extra_body=kwargs.get("extra_body"),
                metadata=kwargs.get("metadata"),
                caching=kwargs.get("caching", False),
            )

        engine_cls.embedding = staticmethod(patched_embedding)  # pyrefly: ignore[missing-attribute]

    @staticmethod
    def _patch_neo4j_adapter(adapter_cls: type) -> None:
        """Wrap Neo4j adapter methods to fallback when APOC procedures are unavailable."""
        import re
        from collections import defaultdict
        from typing import Any

        from neo4j.exceptions import Neo4jError

        try:
            from cognee.infrastructure.databases.graph.neo4j_driver.adapter import BASE_LABEL
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"neo4j_adapter_patch_skipped detail={exc}")
            return

        label_pattern = re.compile(r"[^0-9A-Za-z_]")

        def _sanitize_label(label: str) -> str:
            sanitized = label_pattern.sub("_", label or "Node")
            if sanitized and sanitized[0].isdigit():
                sanitized = f"_{sanitized}"
            return sanitized or "Node"

        async def _add_node_without_apoc(self, node):
            label = _sanitize_label(type(node).__name__)
            serialized_properties = self.serialize_properties(node.model_dump())
            query = dedent(
                f"""MERGE (n:`{BASE_LABEL}` {{id: $node_id}})
                ON CREATE SET n += $properties, n.updated_at = timestamp()
                ON MATCH SET n += $properties, n.updated_at = timestamp()
                SET n:`{label}`
                RETURN ID(n) AS internal_id, n.id AS nodeId"""
            )
            params = {
                "node_id": str(node.id),
                "properties": serialized_properties,
            }
            return await self.query(query, params)

        async def _add_nodes_without_apoc(self, nodes):
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for data_point in nodes:
                label = _sanitize_label(type(data_point).__name__)
                grouped[label].append(
                    {
                        "node_id": str(data_point.id),
                        "properties": self.serialize_properties(dict(data_point)),
                    }
                )
            results: list[Any] = []
            for label, payload in grouped.items():
                logger.info(f"neo4j_add_nodes_fallback label={label} count={len(payload)}")
                query = dedent(
                    f"""
                    UNWIND $nodes AS node
                    MERGE (n:`{BASE_LABEL}` {{id: node.node_id}})
                    ON CREATE SET n += node.properties, n.updated_at = timestamp()
                    ON MATCH SET n += node.properties, n.updated_at = timestamp()
                    SET n:`{label}`
                    RETURN ID(n) AS internal_id, n.id AS nodeId
                    """
                )
                results.extend(await self.query(query, {"nodes": payload}))
            return results

        original_add_node = adapter_cls.add_node
        original_add_nodes = adapter_cls.add_nodes

        async def patched_add_node(self, node):  # type: ignore[override]
            logger.info(f"neo4j_add_node label={type(node).__name__}")
            try:
                return await original_add_node(self, node)
            except Neo4jError as exc:  # pragma: no cover
                if "apoc.create.addLabels" not in str(exc):
                    raise
                logger.warning("neo4j_apoc_missing falling back to manual label assignment")
                return await _add_node_without_apoc(self, node)

        async def patched_add_nodes(self, nodes):  # type: ignore[override]
            logger.info(f"neo4j_add_nodes total={len(nodes)}")
            try:
                return await original_add_nodes(self, nodes)
            except Neo4jError as exc:  # pragma: no cover
                if "apoc.create.addLabels" not in str(exc):
                    raise
                logger.warning("neo4j_apoc_missing falling back to manual label assignment")
                return await _add_nodes_without_apoc(self, nodes)

        adapter_cls.add_node = patched_add_node  # type: ignore[attr-defined]
        adapter_cls.add_nodes = patched_add_nodes  # type: ignore[attr-defined]

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

    @staticmethod
    def _patch_graph_logging() -> None:
        return

    @staticmethod
    def _patch_add_data_points_logging() -> None:
        return

    @staticmethod
    def _patch_extract_graph_task() -> None:
        return

    @staticmethod
    def _patch_cognify_tasks() -> None:
        """Ensure graph tasks are present in cognify pipelines."""
        try:
            import cognee.api.v1.cognify.cognify as cognify_module
            from cognee.api.v1.cognify.cognify import get_default_tasks as original_get_tasks
            from cognee.api.v1.cognify.cognify import get_temporal_tasks as original_temporal_tasks
            from cognee.modules.pipelines.tasks.task import Task as CogneeTask
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"cognify task patch skipped detail={exc}")
            return

        def _task_name(task: Any) -> str:
            callable_obj = getattr(task, "callable", None) or getattr(task, "executable", None)
            if callable_obj is not None:
                return getattr(callable_obj, "__name__", str(callable_obj))
            return getattr(task, "__name__", str(task))

        def _build_task(executable: Any) -> Any:
            if executable is None:
                return None
            if isinstance(executable, CogneeTask):
                return executable
            try:
                return CogneeTask(executable=executable)
            except Exception:
                pass
            try:
                return CogneeTask(callable=executable)
            except Exception:
                return executable

        def _resolve_graph_task() -> Any | None:
            try:
                from cognee.tasks.graph import extract_graph_from_data
            except Exception:
                extract_graph_from_data = None
            if extract_graph_from_data is not None:
                return _build_task(extract_graph_from_data)
            return None

        def _ensure_graph_tasks(tasks: list[Any]) -> list[Any]:
            names = [_task_name(task) for task in tasks]
            if any("extract_graph" in name for name in names):
                return tasks
            graph_task = _resolve_graph_task()
            if graph_task is None:
                return tasks
            tasks.append(graph_task)
            return tasks

        if callable(original_get_tasks):

            async def logged_get_default_tasks(*args: Any, **kwargs: Any):
                tasks = list(await original_get_tasks(*args, **kwargs))
                tasks = _ensure_graph_tasks(tasks)
                return tasks

            cognify_module.get_default_tasks = logged_get_default_tasks

        if callable(original_temporal_tasks):

            async def logged_temporal_tasks(*args: Any, **kwargs: Any):
                tasks = list(await original_temporal_tasks(*args, **kwargs))
                tasks = _ensure_graph_tasks(tasks)
                return tasks

            cognify_module.get_temporal_tasks = logged_temporal_tasks

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
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Patch dataset creation failed: {exc}")

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
                    return [entry for entry in (res or []) if getattr(entry, "id", None)]

                setattr(m_all, "get_all_user_permission_datasets", safe_all)

            if callable(orig_auth):
                original_auth = cast(Callable[[list[Any], str, Any], Awaitable[list[Any] | None]], orig_auth)

                async def safe_auth(datasets: list[Any], permission_type: str, user: Any) -> list[Any]:
                    try:
                        res = await original_auth(datasets, permission_type, user)
                    except Exception:
                        return []
                    return [entry for entry in (res or []) if getattr(entry, "id", None)]

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
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Patch RBAC resolvers failed: {exc}")

    @staticmethod
    def _render_safe_url(raw_url: str | None) -> str:
        if not raw_url:
            return "unset"
        try:
            parsed = make_url(raw_url)
            return parsed.render_as_string(hide_password=True)
        except Exception:
            return raw_url

    @staticmethod
    def _extract_url_meta(raw_url: str) -> dict[str, str | int | None]:
        try:
            parsed: URL = make_url(raw_url)
        except Exception:
            return {}
        return {
            "host": parsed.host,
            "port": parsed.port,
            "database": parsed.database,
            "username": parsed.username,
            "password": parsed.password,
        }
