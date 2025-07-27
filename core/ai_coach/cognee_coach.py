from __future__ import annotations

import asyncio
import logging
import os
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple
import json
from uuid import uuid4

from core.ai_coach.lock_cache import LockCache

import cognee
from cognee.modules.data.exceptions import DatasetNotFoundError
from cognee.modules.users.exceptions.exceptions import PermissionDeniedError
from cognee.modules.users.methods.get_default_user import get_default_user
from cognee.infrastructure.databases.exceptions import DatabaseNotCreatedError
from cognee.modules.engine.operations.setup import setup as cognee_setup
from sqlalchemy.exc import SAWarning
from loguru import logger

from config.app_settings import settings
from config.logger import configure_loguru
from core.ai_coach.base import BaseAICoach
from core.ai_coach.knowledge_loader import KnowledgeLoader
from core.ai_coach.prompts import INITIAL_PROMPT, UPDATE_WORKOUT_PROMPT, SYSTEM_MESSAGE
from core.schemas import Client


OPENROUTER_API_KEY = "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"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

OPENAI_API_KEY = (
    "sk-svcacct-rtE7qv2lBdDw1f1HaEGhi2WkbG3A__bylo3J2EU4rRpLLnoq7hNzJpE5yjL0Gy96H-"
    "lpymdmT3BlbkFJl75ntMwuTInpuzpYhy8de6lgxWyq9Z6T_KC27GgidEYVvyCblmPU5XmT5H4sK5KvY"
    "xqGpGcA"
)
OPENAI_BASE_URL    = "https://api.openai.com/v1"
EMBEDDING_MODEL    = "openai/text-embedding-3-large"  # работает в Cognee ≥0.27
OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://gymbot.local",
    "X-Title": "GymBot",
}


@dataclass
class CogneeConfig:
    api_key: str
    model: str
    provider: str
    endpoint: str
    vector_provider: str
    vector_url: str
    graph_provider: str
    graph_prompt_path: str
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str

    def apply(self) -> None:
        self._configure_environment()
        self._configure_logging()
        self._patch_cognee()
        self._configure_llm()
        self._configure_vector_db()
        self._configure_graph_db()
        self._configure_relational_db()

    def _configure_llm(self) -> None:
        """
        Чат-LLM → OpenRouter; эмбединги → OpenAI.
        """
        # 🗣️ LLM (OpenRouter)
        cognee.config.set_llm_provider("custom")
        cognee.config.set_llm_model("openrouter/deepseek/deepseek-chat-v3-0324:free")
        cognee.config.set_llm_api_key(OPENROUTER_API_KEY)
        cognee.config.set_llm_endpoint(OPENROUTER_BASE_URL)

        # 📐 Embeddings (ENV читает Cognee → LiteLLM)
        os.environ["EMBEDDING_PROVIDER"] = "openai"
        os.environ["EMBEDDING_MODEL"] = EMBEDDING_MODEL
        os.environ["EMBEDDING_ENDPOINT"] = OPENAI_BASE_URL
        os.environ["EMBEDDING_API_KEY"] = OPENAI_API_KEY

    def _configure_vector_db(self) -> None:
        cognee.config.set_vector_db_provider(self.vector_provider)
        cognee.config.set_vector_db_url(self.vector_url)

    def _configure_graph_db(self) -> None:
        os.environ["GRAPH_PROMPT_PATH"] = Path(self.graph_prompt_path).resolve().as_posix()
        os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
        cognee.config.set_graph_database_provider(self.graph_provider)
        cognee.config.set_llm_config({"graph_prompt_path": os.environ["GRAPH_PROMPT_PATH"]})

    def _configure_relational_db(self) -> None:
        cognee.config.set_relational_db_config(
            {
                "db_host": self.db_host,
                "db_port": self.db_port,
                "db_username": self.db_user,
                "db_password": self.db_password,
                "db_name": self.db_name,
                "db_path": "",
                "db_provider": "postgres",
            }
        )

    @staticmethod
    def _patch_cognee() -> None:
        """
        • UUID PK для GraphRelationshipLedger
        • Фикс эмбедингов на OpenAI
        • Добавляем обязательные заголовки к OpenRouter-клиенту
        """
        try:
            from cognee.modules.data.models.graph_relationship_ledger import GraphRelationshipLedger
            from cognee.infrastructure.databases.vector.embeddings import LiteLLMEmbeddingEngine
            from cognee.infrastructure.llm.generic_llm_api.adapter import GenericAPIAdapter
            from cognee.infrastructure.files.utils import open_data_file as _orig_open_data_file
            from cognee.infrastructure.files import utils as file_utils
            from cognee.infrastructure.files.storage.LocalFileStorage import (
                LocalFileStorage,
                get_parsed_path,
            )
            from contextlib import asynccontextmanager
            from openai import AsyncOpenAI

            # 1️⃣ UUID вместо sequence
            from sqlalchemy import schema as sa_schema

            GraphRelationshipLedger.__table__.c.id.default = sa_schema.ColumnDefault(
                uuid4
            )

            async def _patched_embedding(texts, model=None, **kwargs):
                from litellm import embedding
                return await embedding(
                    texts,
                    model=EMBEDDING_MODEL,
                    api_key=OPENAI_API_KEY,
                    base_url=OPENAI_BASE_URL,
                )

            LiteLLMEmbeddingEngine.get_embedding_fn = staticmethod(_patched_embedding)

            _orig_init = GenericAPIAdapter.__init__

            def _new_init(self, *args, **kwargs):
                _orig_init(self, *args, **kwargs)
                client = getattr(self, "aclient", None)
                # AsyncInstructor → .client  |  pure AsyncOpenAI → self
                target = getattr(client, "client", client)
                if isinstance(target, AsyncOpenAI):
                    target.default_headers.update(OPENROUTER_HEADERS)

            GenericAPIAdapter.__init__ = _new_init

            @asynccontextmanager
            async def _fixed_open_data_file(file_path: str, mode: str = "rb", encoding: str | None = None, **kwargs):
                if os.name == "nt" and file_path.startswith("file://") and "\\" in file_path:
                    path_part = file_path[len("file://") :]
                    if not path_part.startswith("/"):
                        path_part = "/" + path_part
                    file_path = "file://" + path_part.replace("\\", "/")
                async with _orig_open_data_file(file_path, mode=mode, encoding=encoding, **kwargs) as f:
                    yield f

            file_utils.open_data_file = _fixed_open_data_file

            _orig_local_open = LocalFileStorage.open

            def _ensure_open(self, file_path: str, mode: str = "rb", *args, **kwargs):
                parsed_storage_path = get_parsed_path(self.storage_path)
                if not os.path.exists(parsed_storage_path):
                    os.makedirs(parsed_storage_path, exist_ok=True)
                return _orig_local_open(self, file_path, mode=mode, *args, **kwargs)

            LocalFileStorage.open = _ensure_open

        except Exception as e:  # noqa: BLE001
            logger.debug(f"Cognee patch failed: {e}")

    # ------------------------------------------------------------------ #
    @staticmethod
    def _configure_environment() -> None:
        """
        Минимальный набор ENV.
        """
        os.environ.setdefault(
            "GRAPH_PROMPT_PATH",
            Path("./core/ai_coach/global_system_prompt.txt").resolve().as_posix(),
        )

        os.environ.setdefault("OPENAI_API_KEY", OPENAI_API_KEY)
        os.environ.setdefault("OPENAI_BASE_URL", OPENAI_BASE_URL)

        os.environ.setdefault("EMBEDDING_PROVIDER", "openai")
        os.environ.setdefault("EMBEDDING_MODEL", EMBEDDING_MODEL)
        os.environ.setdefault("EMBEDDING_ENDPOINT", OPENAI_BASE_URL)
        os.environ.setdefault("EMBEDDING_API_KEY", OPENAI_API_KEY)

        # Логи
        os.environ.setdefault("LITELLM_LOG", "WARNING")
        os.environ.setdefault("LOG_LEVEL", "WARNING")

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


class CogneeCoach(BaseAICoach):
    """
    AI Coach implementation using Cognee for context, memory, and knowledge management.
    """

    _configured: bool = False
    _loader: Optional[KnowledgeLoader] = None
    _cognify_locks: LockCache = LockCache()
    _user: Optional[Any] = None

    @classmethod
    async def initialize(cls) -> None:
        """Ensure database migrations are applied and Cognee is reachable."""
        cls._ensure_config()
        user = await cls._get_user()

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
            env={**os.environ, "DATABASE_URL": settings.VECTORDATABASE_URL},
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

        try:
            await cognee.search("ping", user=user)
        except Exception as e:
            logger.warning(f"Cognee ping failed: {e}")

    @classmethod
    async def _get_user(cls) -> Any:
        """
        Retrieve and cache the default Cognee user.
        """
        if cls._user is None:
            try:
                cls._user = await get_default_user()
            except DatabaseNotCreatedError:
                await cognee_setup()
                cls._user = await get_default_user()
        return cls._user

    @classmethod
    def _ensure_config(cls) -> None:
        """Apply Cognee configuration only once."""
        if not cls._configured:
            CogneeConfig(
                api_key=settings.COGNEE_API_KEY,
                model=settings.COGNEE_MODEL,
                provider=settings.COGNEE_LLM_PROVIDER,
                endpoint=settings.COGNEE_API_URL,
                vector_provider=settings.VECTORDATABASE_PROVIDER,
                vector_url=settings.VECTORDATABASE_URL,
                graph_provider=settings.GRAPH_DATABASE_PROVIDER,
                graph_prompt_path=settings.GRAPH_PROMPT_PATH,
                db_host=settings.DB_HOST,
                db_port=settings.DB_PORT,
                db_user=settings.DB_USER,
                db_password=settings.DB_PASSWORD,
                db_name=settings.DB_NAME,
            ).apply()
            cls._configured = True

    @classmethod
    async def init_loader(cls, loader: KnowledgeLoader) -> None:
        cls._loader = loader
        await cls.refresh_knowledge_base()

    @classmethod
    async def refresh_knowledge_base(cls) -> None:
        """Reload external knowledge and rebuild Cognee index."""
        cls._ensure_config()
        if cls._loader:
            await cls._loader.refresh()
        try:
            await cognee.cognify()
        except DatasetNotFoundError:
            logger.warning("No datasets found to process")
        except PermissionDeniedError as e:
            logger.error(f"Permission denied while updating knowledge base: {e}")

    @staticmethod
    async def _safe_add(text: str, dataset: str, user: Any) -> Tuple[str, bool]:  # (dataset_id, created_now)
        """Safely add text to a Cognee dataset."""
        logger.trace(f"_safe_add → dataset={dataset!r}")
        if not text.strip():
            return dataset, False

        try:
            info = await cognee.add(text, dataset_name=dataset, user=user)
            return getattr(info, "dataset_id", dataset), True
        except PermissionDeniedError:
            new_name = f"{dataset}_{uuid4().hex[:8]}"
            logger.trace(f"PermissionDenied on {dataset}, retrying as {new_name}")
            info = await cognee.add(text, dataset_name=new_name, user=user)
            return getattr(info, "dataset_id", new_name), True

    @staticmethod
    def _make_initial_prompt(client_data: str, lang: str) -> str:
        return INITIAL_PROMPT.format(client_data=client_data, language=lang)

    @classmethod
    async def _cognify_dataset(cls, dataset_id: str, user: Any) -> None:
        lock = cls._cognify_locks.get(dataset_id)
        async with lock:
            await cognee.cognify(datasets=[dataset_id], user=user)

    @classmethod
    async def _add_and_cognify(cls, text: str, dataset: str, user: Any) -> str:
        """Add text to dataset and trigger background cognification if created."""
        ds_id, created = await cls._safe_add(text, dataset, user)
        if created:
            asyncio.create_task(cls._cognify_dataset(ds_id, user))
        return ds_id

    @classmethod
    async def get_context(cls, chat_id: int, query: str) -> list[str]:
        cls._ensure_config()
        user = await cls._get_user()
        base = f"chat_{chat_id}_{user.id}"
        try:
            ds_id, _ = await cls._safe_add("init", base, user)
            return await cognee.search(query, datasets=[ds_id], top_k=5, user=user)
        except Exception as e:
            logger.error(f"get_context failed: {e}")
            return []

    @classmethod
    async def make_request(cls, prompt: str, *, client: Optional[Client] = None) -> list[str]:
        """Store history and query Cognee."""
        cls._ensure_config()
        user = await cls._get_user()
        print(f"Final prompt: {prompt}")  # TODO: REMOVE
        dataset_base = "main_dataset" if client is None else f"main_dataset_{client.id}"
        dataset_name = f"{dataset_base}_{user.id}"

        try:
            ds_id = await cls._add_and_cognify(prompt, dataset_name, user)
            return await cognee.search(prompt, datasets=[ds_id], user=user)
        except PermissionDeniedError as e:
            logger.error(f"Permission denied: {e}")
        except DatasetNotFoundError:
            logger.error("Search failed: dataset not found")
        except Exception as e:
            logger.error(f"Unexpected AI coach error during client {client.id} request: {e}")
        return []

    @classmethod
    async def assign_client(cls, client: Client, lang: str) -> None:
        prompt = cls._make_initial_prompt(cls._extract_client_data(client), lang)
        await cls.make_request(prompt)

    @classmethod
    async def save_user_message(cls, text: str, chat_id: int, client_id: int) -> None:
        """Store a raw user message into the chat history dataset."""
        if not text.strip():
            return
        cls._ensure_config()
        user = await cls._get_user()
        ds_name = f"chat_{chat_id}_{user.id}"
        await cls._add_and_cognify(text, ds_name, user)

    @classmethod
    async def process_workout_result(
        cls,
        client_id: int,
        expected_workout_result: str,
        feedback: str,
        language: str,
    ) -> str:
        """Update workout plan based on client's feedback and previous context."""

        cls._ensure_config()

        try:
            ctx = await cls.get_context(client_id, "workout")
        except Exception:
            ctx = []

        prompt = (
            SYSTEM_MESSAGE
            + "\n\n"
            + UPDATE_WORKOUT_PROMPT.format(
                expected_workout=expected_workout_result.strip(),
                feedback=feedback.strip(),
                context="\n".join(ctx).strip(),
                language=language,
            )
        )

        responses = await cls.make_request(prompt=prompt, client=None)
        return responses[0] if responses else ""

    @staticmethod
    def _extract_client_data(client: Client) -> str:
        details = {
            "name": client.name,
            "gender": client.gender,
            "born_in": client.born_in,
            "weight": client.weight,
            "health_notes": client.health_notes,
            "workout_experience": client.workout_experience,
            "workout_goals": client.workout_goals,
        }
        clean = {k: v for k, v in details.items() if v is not None}
        return json.dumps(clean, ensure_ascii=False)
