from __future__ import annotations

import os
import sys
import asyncio
import warnings
import logging
from dataclasses import dataclass
from typing import Optional
from pathlib import Path

from sqlalchemy.exc import SAWarning

from loguru import logger
from config.logger import configure_loguru

from config.env_settings import settings
from core.ai_coach.base import BaseAICoach
from core.ai_coach.knowledge_loader import KnowledgeLoader
from core.schemas import Client

# Ensure the graph prompt path environment variable is set before importing
# cognee so that its configuration picks up the correct value on import.

default_prompt = os.environ.get("GRAPH_PROMPT_PATH", "./core/ai_coach/global_system_prompt.txt")
prompt_file = Path(default_prompt).resolve()
os.environ["GRAPH_PROMPT_PATH"] = prompt_file.as_posix()

# Silence repetitive SQLAlchemy warnings from dlt which clutter the logs
warnings.filterwarnings(
    "ignore",
    message="Table 'file_metadata' already exists within the given MetaData",
    category=SAWarning,
)
warnings.filterwarnings(
    "ignore",
    message="Table '_dlt_pipeline_state' already exists within the given MetaData",
    category=SAWarning,
)
warnings.filterwarnings(
    "ignore",
    message="implicitly coercing SELECT object to scalar subquery",
    category=SAWarning,
)
warnings.filterwarnings(
    "ignore",
    message="This declarative base already contains a class with the same class name",
    category=SAWarning,
)

# Silence noisy warnings from langfuse when no API key is provided
logging.getLogger("langfuse").setLevel(logging.ERROR)

import cognee  # noqa: E402
from cognee.modules.data.exceptions import DatasetNotFoundError  # noqa: E402


os.environ.setdefault("LITELLM_LOG", "WARNING")
os.environ.setdefault("LOG_LEVEL", "WARNING")


LANGUAGE_NAMES = {"ua": "Ukrainian", "ru": "Russian", "eng": "English"}


configure_loguru()


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
        cognee.config.set_llm_provider(self.provider)
        cognee.config.set_llm_model(self.model)
        cognee.config.set_llm_api_key(self.api_key)
        cognee.config.set_llm_endpoint(self.endpoint)

        cognee.config.set_vector_db_provider(self.vector_provider)
        cognee.config.set_vector_db_url(self.vector_url)
        cognee.config.set_graph_database_provider(self.graph_provider)
        prompt_file = Path(self.graph_prompt_path).resolve()
        if not prompt_file.is_file():
            raise FileNotFoundError(f"System prompt file not found: {prompt_file}")
        posix_path = prompt_file.as_posix()
        os.environ["GRAPH_PROMPT_PATH"] = posix_path
        cognee.config.set_llm_config({"graph_prompt_path": posix_path})

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

        logger.info("Cognee successfully configured")


class CogneeCoach(BaseAICoach):
    _configured: bool = False
    _loader: Optional[KnowledgeLoader] = None

    @classmethod
    async def initialize(cls) -> None:
        try:
            cls._ensure_config()
        except Exception as e:
            logger.warning(f"Cognee initialization failed: {e}")
            return

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
            env={
                **os.environ,
                "DATABASE_URL": settings.VECTORDATABASE_URL,
            },
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await process.wait()

        try:
            await cognee.search("ping")
        except Exception as e:
            logger.warning(f"Cognee ping failed: {e}")

    @classmethod
    def set_loader(cls, loader: KnowledgeLoader) -> None:
        """Register a loader instance for fetching external knowledge."""
        cls._loader = loader

    @classmethod
    async def init_loader(cls, loader: KnowledgeLoader) -> None:
        """Register ``loader`` and refresh the knowledge base."""
        cls.set_loader(loader)
        await cls.refresh_knowledge_base()

    @classmethod
    def _ensure_config(cls) -> None:
        """Ensure Cognee is configured."""
        if cls._configured:
            return

        config = CogneeConfig(
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
        )
        config.apply()
        cls._configured = True

    @staticmethod
    def _extract_client_data(client: Client) -> str:
        """Extract client data from the client object."""
        details = {
            "name": client.name,
            "gender": client.gender,
            "born_in": client.born_in,
            "weight": client.weight,
            "health_notes": client.health_notes,
            "workout_experience": client.workout_experience,
            "workout_goals": client.workout_goals,
        }
        parts = [f"{k}: {v}" for k, v in details.items() if v]
        return "; ".join(parts)

    @staticmethod
    def _make_initial_prompt(client_data: str) -> str:
        """Create the initial prompt based on the client data."""
        return "\n".join(
            [
                "Memorize the following client profile information and use it as context for all future responses.",
                client_data,
            ]
        )

    @classmethod
    async def coach_request(
        cls,
        text: str,
        *,
        client: Client | None = None,
        chat_id: int | None = None,
        language: str | None = None,
    ) -> list:
        cls._ensure_config()

        prompt_parts = []
        if client is not None:
            client_data = cls._extract_client_data(client)
            if client_data:
                prompt_parts.append(f"Client info: {client_data}")
            try:
                from core.cache import Cache

                program = await Cache.workout.get_program(client.profile, use_fallback=False)
                prompt_parts.append(f"Latest program: {program.workout_type}, split {program.split_number}")
                sub = await Cache.workout.get_latest_subscription(client.profile, use_fallback=False)
                prompt_parts.append(f"Active subscription: {sub.workout_type} {sub.workout_days} period {sub.period}")
            except Exception:
                pass

        if chat_id is not None:
            try:
                history = await cls.get_context(chat_id, text)
                if history:
                    prompt_parts.append("\n".join(history))
            except Exception:
                pass

        prompt_parts.append(text)
        if language:
            lang_name = LANGUAGE_NAMES.get(language, language)
            prompt_parts.append(f"Answer in {lang_name}.")
        final_prompt = "\n".join(prompt_parts)

        dataset = "main_dataset"
        if client is not None:
            dataset = f"main_dataset_{client.id}"
        logger.debug(
            f"Adding prompt to dataset {dataset}: {final_prompt[:100]}"
        )
        dataset_info = await cognee.add(final_prompt, dataset_name=dataset)
        dataset_id = str(getattr(dataset_info, "dataset_id", dataset_info))
        logger.debug(
            f"Running cognify on dataset {dataset_id} ({dataset})"
        )
        try:
            await cognee.cognify(datasets=[dataset])
        except DatasetNotFoundError:
            logger.warning("No datasets found to process")
            return []
        logger.debug(f"Searching dataset {dataset_id} for response")
        try:
            return await cognee.search(final_prompt, datasets=[dataset])
        except DatasetNotFoundError:
            logger.error("Search failed, dataset not found")
            return []

    @classmethod
    async def refresh_knowledge_base(cls) -> None:
        """Reload external knowledge via the registered loader."""
        cls._ensure_config()
        if cls._loader is None:
            return
        await cls._loader.refresh()
        await cls.update_knowledge_base()

    @classmethod
    async def update_knowledge_base(cls) -> None:
        cls._ensure_config()
        try:
            await cognee.cognify()
        except DatasetNotFoundError:
            logger.warning("No datasets found to process")

    @classmethod
    async def assign_client(cls, client: Client) -> None:
        client_data = cls._extract_client_data(client)
        prompt = cls._make_initial_prompt(client_data)
        await cls.coach_request(prompt)

    @classmethod
    async def save_user_message(cls, text: str, chat_id: int, client_id: int) -> None:
        """Persist user message in Cognee memory."""
        if not text.strip():
            return
        cls._ensure_config()
        dataset = f"chat_{chat_id}"
        await cognee.add(text, dataset_name=dataset)
        try:
            await cognee.cognify(datasets=[dataset])
        except DatasetNotFoundError:
            logger.warning("No datasets found to process")

    @classmethod
    async def get_context(cls, chat_id: int, query: str) -> list:
        """Retrieve context for ``query`` from chat history."""
        cls._ensure_config()
        dataset = f"chat_{chat_id}"
        return await cognee.search(query, datasets=[dataset], top_k=5)

    @classmethod
    async def process_workout_result(cls, client_id: int, feedback: str, language: str | None = None) -> str:
        """Generate an updated workout program based on ``feedback``."""

        cls._ensure_config()
        context = []
        try:
            context = await cls.get_context(client_id, "workout")
        except Exception:
            context = []

        prompt_parts = [feedback]
        if context:
            prompt_parts.append("\n".join(context))
        prompt_parts.append("Update the workout plan accordingly.")
        response = await cls.coach_request("\n".join(prompt_parts), chat_id=client_id, language=language)
        return response[0] if response else ""
