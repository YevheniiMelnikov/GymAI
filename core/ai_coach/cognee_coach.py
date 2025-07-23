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

import cognee
from cognee.modules.data.exceptions import DatasetNotFoundError
from cognee.modules.users.exceptions.exceptions import PermissionDeniedError
from cognee.modules.users.methods.get_default_user import get_default_user
from sqlalchemy.exc import SAWarning
from loguru import logger

from config.env_settings import settings
from config.logger import configure_loguru
from core.ai_coach.base import BaseAICoach
from core.ai_coach.knowledge_loader import KnowledgeLoader
from core.ai_coach.prompts import INITIAL_PROMPT
from core.ai_coach.parsers import parse_program_json, parse_program_text
from core.cache import Cache
from core.exceptions import SubscriptionNotFoundError
from core.schemas import Client
from core.services.internal import APIService


def _patch_cognee() -> None:
    """Fix issues in Cognee's graph ledger ID generation."""
    try:
        from cognee.modules.data.models.graph_relationship_ledger import GraphRelationshipLedger

        GraphRelationshipLedger.__table__.c.id.default = uuid4
    except Exception as e:
        logger.debug(f"GraphRelationshipLedger patch failed: {e}")


def configure_environment() -> None:
    """
    Set up environment variables for graph prompt and logging defaults.
    """
    default_prompt = os.environ.get("GRAPH_PROMPT_PATH", "./core/ai_coach/global_system_prompt.txt")
    os.environ["GRAPH_PROMPT_PATH"] = Path(default_prompt).resolve().as_posix()
    os.environ.setdefault("LITELLM_LOG", "WARNING")
    os.environ.setdefault("LOG_LEVEL", "WARNING")


def configure_logging() -> None:
    """
    Configure warnings, standard logging, and loguru for consistent output.
    """
    warnings.filterwarnings("ignore", category=SAWarning)
    logging.getLogger("langfuse").setLevel(logging.ERROR)
    configure_loguru()
    # Suppress verbose Cognee logs
    logger.level("COGNEE", no=45, color="<cyan>")
    logging.getLogger("cognee").setLevel(logging.INFO)


# Initialize environment and logging at import
configure_environment()
configure_logging()
_patch_cognee()


async def _safe_add(text: str, dataset: str, user: Any) -> Tuple[str, bool]:  # (dataset_id, created_now)
    """
    Safely add text to a Cognee dataset.
    Retries with a new dataset name on PermissionDeniedError.
    """
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
        self._configure_llm()
        self._configure_vector_db()
        self._configure_graph_db()
        self._configure_relational_db()

    def _configure_llm(self) -> None:
        cognee.config.set_llm_provider(self.provider)
        cognee.config.set_llm_model(self.model)
        cognee.config.set_llm_api_key(self.api_key)
        cognee.config.set_llm_endpoint(self.endpoint)

    def _configure_vector_db(self) -> None:
        cognee.config.set_vector_db_provider(self.vector_provider)
        cognee.config.set_vector_db_url(self.vector_url)

    def _configure_graph_db(self) -> None:
        os.environ["GRAPH_PROMPT_PATH"] = Path(self.graph_prompt_path).resolve().as_posix()
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


class CogneeCoach(BaseAICoach):
    """
    AI Coach implementation using Cognee for context, memory, and knowledge management.
    """

    _configured: bool = False
    _loader: Optional[KnowledgeLoader] = None
    _cognify_locks: dict[str, asyncio.Lock] = {}
    _user: Optional[Any] = None

    @classmethod
    async def initialize(cls) -> None:
        """
        Ensure database migrations are applied and Cognee is reachable.
        """
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
            cls._user = await get_default_user()
        return cls._user

    @classmethod
    def _ensure_config(cls) -> None:
        """
        Apply Cognee configuration only once.
        """
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
        """
        Reload external knowledge and rebuild Cognee index.
        """
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

    @staticmethod
    def _make_initial_prompt(client_data: str) -> str:
        return INITIAL_PROMPT.format(client_data=client_data)

    @classmethod
    async def _cognify_dataset(cls, dataset_id: str, user: Any) -> None:
        lock = cls._cognify_locks.setdefault(dataset_id, asyncio.Lock())
        async with lock:
            await cognee.cognify(datasets=[dataset_id], user=user)

    @classmethod
    async def _add_and_cognify(cls, text: str, dataset: str, user: Any) -> str:
        """
        Add text to dataset and trigger background cognification if created.
        """
        ds_id, created = await _safe_add(text, dataset, user)
        if created:
            asyncio.create_task(cls._cognify_dataset(ds_id, user))
        return ds_id

    @classmethod
    async def get_context(cls, chat_id: int, query: str) -> list[str]:
        cls._ensure_config()
        user = await cls._get_user()
        base = f"chat_{chat_id}_{user.id}"
        try:
            ds_id, _ = await _safe_add("init", base, user)
            return await cognee.search(query, datasets=[ds_id], top_k=5, user=user)
        except Exception as e:
            logger.error(f"get_context failed: {e}")
            return []

    @classmethod
    async def make_request(
        cls,
        text: str,
        *,
        client: Optional[Client] = None,
        chat_id: Optional[int] = None,
        language: Optional[str] = None,
    ) -> list[str]:
        """
        Build prompt, store history, and query Cognee.
        """
        cls._ensure_config()
        user = await cls._get_user()

        final_prompt = text
        print(f"Final prompt: {final_prompt}")
        dataset_base = "main_dataset" if client is None else f"main_dataset_{client.id}"
        dataset_name = f"{dataset_base}_{user.id}"

        try:
            ds_id = await cls._add_and_cognify(final_prompt, dataset_name, user)
        except PermissionDeniedError as e:
            logger.error(f"Permission denied while adding data: {e}")
            return []
        except Exception as e:
            logger.error(f"Failed to add data: {e}")
            return []

        try:
            return await cognee.search(final_prompt, datasets=[ds_id], user=user)
        except DatasetNotFoundError:
            logger.error("Search failed, dataset not found")
        except PermissionDeniedError as e:
            logger.error(f"Permission denied during search: {e}")
        return []

    @classmethod
    async def assign_client(cls, client: Client) -> None:
        prompt = cls._make_initial_prompt(cls._extract_client_data(client))
        await cls.make_request(prompt)

    @classmethod
    async def save_user_message(cls, text: str, chat_id: int, client_id: int) -> None:
        """
        Store a raw user message into the chat history dataset.
        """
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
        feedback: str,
        language: Optional[str] = None,
    ) -> str:
        """
        Update workout plan based on feedback and previous context.
        """
        cls._ensure_config()
        try:
            ctx = await cls.get_context(client_id, "workout")
        except Exception:
            ctx = []

        prompt_parts = [
            feedback,
            *ctx,
            "Update the workout plan accordingly.",
        ]  # TODO: CREATE DETAILED PROMPT FOR REQUEST
        responses = await cls.make_request(
            "\n".join(prompt_parts), chat_id=client_id, language=language
        )
        result = responses[0] if responses else ""

        if not result:
            return ""

        dto = parse_program_json(result)
        if dto is not None:
            exercises = dto.days
        else:
            exercises, _ = parse_program_text(result)

        if not exercises:
            logger.error("AI workout update produced no exercises")
            return result

        try:
            subscription = await Cache.workout.get_latest_subscription(client_id)
        except SubscriptionNotFoundError:
            logger.error(f"No subscription found for client_id={client_id}")
            return result

        serialized = [day.model_dump() for day in exercises]
        subscription_data = subscription.model_dump()
        subscription_data.update(client_profile=client_id, exercises=serialized)

        await APIService.workout.update_subscription(subscription.id, subscription_data)
        await Cache.workout.update_subscription(
            client_id,
            {"exercises": serialized, "client_profile": client_id},
        )
        return result
