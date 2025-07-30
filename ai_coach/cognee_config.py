from __future__ import annotations

import logging
import os
import warnings
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
from typing import Any

from cognee.base_config import get_base_config

import cognee
from loguru import logger
from sqlalchemy.exc import SAWarning

from config import configure_loguru
from config.app_settings import settings


class CogneeConfig:
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
        try:
            from contextlib import asynccontextmanager
            from openai import AsyncOpenAI
            from sqlalchemy import schema as sa_schema

            from cognee.modules.data.models.graph_relationship_ledger import GraphRelationshipLedger
            from cognee.infrastructure.databases.vector.embeddings import LiteLLMEmbeddingEngine
            from cognee.infrastructure.llm.generic_llm_api.adapter import GenericAPIAdapter
            from cognee.infrastructure.files.utils import open_data_file as _orig_open_data_file
            from cognee.infrastructure.files.storage.LocalFileStorage import (
                LocalFileStorage,
                get_parsed_path,
            )

            GraphRelationshipLedger.__table__.c.id.default = sa_schema.ColumnDefault(uuid4)

            async def _patched_embedding(texts, model=None, **kwargs) -> Any:
                from litellm import embedding
                return await embedding(
                    texts,
                    model=settings.EMBEDDING_MODEL,
                    api_key=settings.OPENAI_API_KEY,
                    base_url=settings.OPENAI_BASE_URL,
                )

            LiteLLMEmbeddingEngine.get_embedding_fn = staticmethod(_patched_embedding)

            _orig_init = GenericAPIAdapter.__init__

            def _new_init(self, *args, **kwargs) -> None:
                _orig_init(self, *args, **kwargs)
                target = getattr(getattr(self, "aclient", None), "client", None) or getattr(self, "aclient", None)
                if isinstance(target, AsyncOpenAI):
                    target.default_headers.update({"HTTP-Referer": "https://gymbot.local", "X-Title": "GymBot"})

            GenericAPIAdapter.__init__ = _new_init

            @asynccontextmanager
            async def _fixed_open_data_file(
                file_path: str,
                mode: str = "rb",
                encoding: str | None = None,
                **kwargs,
            ):
                raw_win_path = ":" in file_path and "\\" in file_path
                uri_scheme = file_path.startswith("file://")

                if raw_win_path:
                    file_path = "file://" + file_path.replace("\\", "/")

                if uri_scheme or raw_win_path:
                    parsed_url = urlparse(file_path)
                    path_str = parsed_url.path or parsed_url.netloc
                    path_str = path_str.replace("\\", "/")
                    if path_str.startswith("/") and len(path_str) > 2 and path_str[2] == ":":
                        path_str = path_str[1:]
                    parsed_path = Path(path_str.lstrip("/"))
                    fs_path = parsed_path if parsed_path.is_absolute() else parsed_path.absolute()
                    if not fs_path.exists():
                        data_root = Path(get_base_config().data_root_directory)
                        fs_path = data_root / parsed_path.name
                    storage = LocalFileStorage(str(fs_path.parent))
                    with storage.open(fs_path.name, mode=mode, encoding=encoding, **kwargs) as f:
                        yield f
                else:
                    async with _orig_open_data_file(
                        file_path, mode=mode, encoding=encoding, **kwargs
                    ) as f:
                        yield f

            import cognee.infrastructure.files.utils as file_utils

            file_utils.open_data_file = _fixed_open_data_file

            _orig_local_open = LocalFileStorage.open

            def _ensure_open(self, file_path: str, mode: str = "rb", *args, **kwargs):
                raw_storage_path = get_parsed_path(self.storage_path)
                safe_path = Path(raw_storage_path).absolute()
                safe_path.mkdir(parents=True, exist_ok=True)
                self.storage_path = str(safe_path)
                return _orig_local_open(self, file_path, mode=mode, *args, **kwargs)

            LocalFileStorage.open = _ensure_open
        except Exception as e:
            logger.debug(f"Cognee patch failed: {e}")

    @staticmethod
    def _configure_environment() -> None:
        os.environ.setdefault("GRAPH_PROMPT_PATH", Path("./ai_coach/global_system_prompt.txt").resolve().as_posix())
        os.environ.setdefault("LITELLM_LOG", "WARNING")
        os.environ.setdefault("LOG_LEVEL", "INFO")
        os.environ.setdefault("EMBEDDING_API_KEY", settings.OPENAI_API_KEY)
        try:
            import litellm
            litellm.suppress_debug_info = False
        except Exception:
            pass
        storage_root = Path(".data_storage").resolve()
        storage_root.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("COGNEE_DATA_ROOT", str(storage_root))
        cognee.config.data_root_directory(str(storage_root))

    @staticmethod
    def _configure_logging() -> None:
        warnings.filterwarnings("ignore", category=SAWarning)
        logging.getLogger("langfuse").setLevel(logging.ERROR)
        configure_loguru()
        logger.level("COGNEE", no=45, color="<cyan>")
        logging.getLogger("cognee").setLevel(logging.INFO)
        logging.getLogger("GraphCompletionRetriever").setLevel(logging.ERROR)
