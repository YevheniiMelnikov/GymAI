from __future__ import annotations

import logging
import os
import warnings
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import cognee
from loguru import logger
from sqlalchemy.exc import SAWarning

from config import configure_loguru
from config.app_settings import settings


class CogneeConfig:
    """Configure Cognee for the AI Coach."""

    @classmethod
    def apply(cls) -> None:
        cls._configure_environment()
        cls._configure_logging()
        cls._patch_cognee()
        cls._configure_llm()
        cls._configure_vector_db()
        cls._configure_graph_db()
        cls._configure_relational_db()

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
    def _configure_graph_db() -> None:
        os.environ["GRAPH_PROMPT_PATH"] = Path(settings.GRAPH_PROMPT_PATH).resolve().as_posix()
        cognee.config.set_graph_database_provider(settings.GRAPH_DATABASE_PROVIDER)
        cognee.config.set_llm_config({"graph_prompt_path": os.environ["GRAPH_PROMPT_PATH"]})

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
        """Fix issues in Cognee's start"""
        try:
            from cognee.modules.data.models.graph_relationship_ledger import GraphRelationshipLedger
            from cognee.infrastructure.databases.vector.embeddings import LiteLLMEmbeddingEngine
            from cognee.infrastructure.llm.generic_llm_api.adapter import GenericAPIAdapter
            from cognee.infrastructure.files.utils import open_data_file as _orig_open_data_file
            from cognee.infrastructure.files import utils as file_utils
            from cognee.infrastructure.files.storage.LocalFileStorage import LocalFileStorage, get_parsed_path
            from contextlib import asynccontextmanager
            from openai import AsyncOpenAI

            from sqlalchemy import schema as sa_schema

            GraphRelationshipLedger.__table__.c.id.default = sa_schema.ColumnDefault(uuid4)

            async def _patched_embedding(texts, model=None, **kwargs):
                from litellm import embedding

                return await embedding(
                    texts,
                    model=settings.EMBEDDING_MODEL,
                    api_key=settings.OPENAI_API_KEY,
                    base_url=settings.OPENAI_BASE_URL,
                )

            LiteLLMEmbeddingEngine.get_embedding_fn = staticmethod(_patched_embedding)

            _orig_init = GenericAPIAdapter.__init__

            def _new_init(self, *args, **kwargs):
                _orig_init(self, *args, **kwargs)
                client = getattr(self, "aclient", None)
                target = getattr(client, "client", client)
                if isinstance(target, AsyncOpenAI):
                    openrouter_headers = {
                        "HTTP-Referer": "https://gymbot.local",
                        "X-Title": "GymBot",
                    }
                    target.default_headers.update(openrouter_headers)

            GenericAPIAdapter.__init__ = _new_init

            @asynccontextmanager
            async def _fixed_open_data_file(file_path: str, mode: str = "rb", encoding: str | None = None, **kwargs):
                if file_path.startswith("file://"):
                    parsed = urlparse(file_path)
                    fs_path = parsed.path or parsed.netloc
                    if os.name == "nt":
                        if fs_path.startswith("/") and len(fs_path) > 2 and fs_path[2] == ":":
                            fs_path = fs_path[1:]
                        fs_path = fs_path.replace("/", "\\")
                    file_dir = os.path.dirname(fs_path)
                    file_name = os.path.basename(fs_path)
                    storage = LocalFileStorage(file_dir)
                    with storage.open(file_name, mode=mode, encoding=encoding, **kwargs) as f:
                        yield f
                else:
                    async with _orig_open_data_file(file_path, mode=mode, encoding=encoding, **kwargs) as f:
                        yield f

            file_utils.open_data_file = _fixed_open_data_file

            _orig_local_open = LocalFileStorage.open

            def _ensure_open(self, file_path: str, mode: str = "rb", *args, **kwargs):
                parsed_storage_path = get_parsed_path(self.storage_path)
                if (
                    os.name == "nt"
                    and parsed_storage_path.startswith("\\")
                    and len(parsed_storage_path) > 2
                    and parsed_storage_path[1] != "\\"
                    and parsed_storage_path[2] == ":"
                ):
                    parsed_storage_path = parsed_storage_path.lstrip("\\")
                if not os.path.exists(parsed_storage_path):
                    os.makedirs(parsed_storage_path, exist_ok=True)
                return _orig_local_open(self, file_path, mode=mode, *args, **kwargs)

            LocalFileStorage.open = _ensure_open

        except Exception as e:  # noqa: BLE001
            logger.debug(f"Cognee patch failed: {e}")

    @staticmethod
    def _configure_environment() -> None:
        """Set up environment variables for graph prompt and logging defaults."""
        os.environ.setdefault(
            "GRAPH_PROMPT_PATH",
            Path("./core/ai_coach/global_system_prompt.txt").resolve().as_posix(),
        )
        os.environ.setdefault("LITELLM_LOG", "ERROR")
        os.environ.setdefault("LOG_LEVEL", "WARNING")
        os.environ.setdefault("EMBEDDING_API_KEY", settings.OPENAI_API_KEY)

        try:
            import litellm

            litellm.suppress_debug_info = True
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Failed to suppress LiteLLM debug info: {exc}")

        storage_root = Path(".data_storage").resolve()
        storage_root.mkdir(parents=True, exist_ok=True)
        cognee.config.data_root_directory(str(storage_root))

    @staticmethod
    def _configure_logging() -> None:
        """Configure warnings, standard logging, and loguru for consistent output."""
        warnings.filterwarnings("ignore", category=SAWarning)
        logging.getLogger("langfuse").setLevel(logging.ERROR)
        configure_loguru()
        logger.level("COGNEE", no=45, color="<cyan>")
        logging.getLogger("cognee").setLevel(logging.INFO)
        logging.getLogger("GraphCompletionRetriever").setLevel(logging.ERROR)
