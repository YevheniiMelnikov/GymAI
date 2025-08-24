from __future__ import annotations

import asyncio
import os
import sys
from hashlib import sha256
from typing import Any, Optional, Tuple

import cognee
from loguru import logger
from cognee.modules.data.exceptions import DatasetNotFoundError
from cognee.modules.users.exceptions.exceptions import PermissionDeniedError
from cognee.modules.users.methods.get_default_user import get_default_user
from cognee.infrastructure.databases.exceptions import DatabaseNotCreatedError
from cognee.modules.engine.operations.setup import setup as cognee_setup

from ai_coach.base_coach import BaseAICoach
from ai_coach.base_knowledge_loader import KnowledgeLoader
from ai_coach.cognee_config import CogneeConfig
from ai_coach.schemas import MessageRole
from ai_coach.hash_store import HashStore
from ai_coach.lock_cache import LockCache
from config.app_settings import settings
from core.exceptions import UserServiceError
from core.services import APIService
from core.schemas import Client


class CogneeCoach(BaseAICoach):
    """
    AI Coach implementation using Cognee for context, memory, and knowledge management.
    """

    _loader: Optional[KnowledgeLoader] = None
    _cognify_locks: LockCache = LockCache()
    _user: Optional[Any] = None

    # shared dataset that stores common knowledge like Google Drive documents
    GLOBAL_DATASET: str = "external_docs"

    @classmethod
    async def initialize(cls, knowledge_loader: KnowledgeLoader | None = None) -> None:
        """
        Initialize Cognee configuration, apply DB migrations and test connectivity.
        """
        CogneeConfig.apply()
        cls._loader = knowledge_loader
        cls._user = await cls._get_cognee_user()
        await cls.refresh_knowledge_base()

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
            await cognee.search("ping", user=cls._user)
        except Exception as e:  # pragma: no cover - best effort
            logger.warning(f"Cognee ping failed: {e}")

    @classmethod
    async def refresh_knowledge_base(cls) -> None:
        """
        Reload external knowledge and rebuild Cognee index.
        """
        if cls._loader:
            await cls._loader.refresh()

        try:
            await cognee.cognify()
        except DatasetNotFoundError:
            logger.warning("No datasets found to process")
        except PermissionDeniedError as e:
            logger.error(f"Permission denied while updating knowledge base: {e}")

    @classmethod
    async def _get_cognee_user(cls) -> Any:
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
    async def make_request(cls, prompt: str, client_id: int) -> list[str]:
        """
        Perform a search across the client's dataset and shared knowledge.
        """
        user = await cls._get_cognee_user()
        await cls._ensure_profile_indexed(client_id, user)
        datasets = [cls._dataset_name(client_id), cls.GLOBAL_DATASET]

        try:
            return await cognee.search(prompt, datasets=datasets, user=user)
        except (PermissionDeniedError, DatasetNotFoundError) as e:
            logger.warning(f"Search issue for client {client_id}: {e}")
        except Exception as e:  # pragma: no cover - best effort
            logger.exception(f"Unexpected error during client {client_id} request: {e}")
        return []

    @staticmethod
    async def update_dataset(
        text: str,
        dataset: str,
        user: Any,
        node_set: list[str] | None = None,
    ) -> Tuple[str, bool]:
        """
        Add text to dataset if not already present.
        Returns (dataset_id, was_created).
        """
        text = text.strip()
        if not text:
            return dataset, False

        digest = sha256(text.encode()).hexdigest()
        if await HashStore.contains(dataset, digest):
            return dataset, False

        info = await cognee.add(text, dataset_name=dataset, user=user, node_set=node_set)
        await HashStore.add(dataset, digest)
        return getattr(info, "dataset_id", dataset), True

    @classmethod
    async def _process_dataset(cls, dataset: str, user: Any) -> None:
        """
        Trigger index update for a dataset, with locking.
        """
        lock = cls._cognify_locks.get(dataset)
        async with lock:
            await cognee.cognify(datasets=[dataset], user=user)

    @staticmethod
    def _dataset_name(client_id: int) -> str:
        return f"client_{client_id}"

    @staticmethod
    def _client_profile_text(client: Client) -> str:
        parts = []
        if client.name:
            parts.append(f"name: {client.name}")
        if client.gender:
            parts.append(f"gender: {client.gender}")
        if client.born_in:
            parts.append(f"born_in: {client.born_in}")
        if client.weight:
            parts.append(f"weight: {client.weight}")
        if client.workout_experience:
            parts.append(f"workout_experience: {client.workout_experience}")
        if client.workout_goals:
            parts.append(f"workout_goals: {client.workout_goals}")
        if client.health_notes:
            parts.append(f"health_notes: {client.health_notes}")
        return "profile: " + "; ".join(parts)

    @classmethod
    async def _ensure_profile_indexed(cls, client_id: int, user: Any) -> None:
        try:
            client = await APIService.profile.get_client_by_profile_id(client_id)
        except UserServiceError as e:
            logger.warning(f"Failed to fetch client profile id={client_id}: {e}")
            return
        if not client:
            return
        text = cls._client_profile_text(client)
        dataset = cls._dataset_name(client_id)
        dataset, created = await cls.update_dataset(text, dataset, user, node_set=["client_profile"])
        if created:
            await cls._process_dataset(dataset, user)

    @classmethod
    async def add_text(
        cls,
        text: str,
        *,
        client_id: int | None,
        role: MessageRole | None = None,
        node_set: list[str] | None = None,
    ) -> None:
        """Add text to the appropriate dataset and trigger indexing if new."""
        user = await cls._get_cognee_user()
        dataset = cls._dataset_name(client_id) if client_id is not None else cls.GLOBAL_DATASET
        if role:
            text = f"{role.value}: {text}"
        dataset, created = await cls.update_dataset(text, dataset, user, node_set=node_set)
        if created:
            asyncio.create_task(cls._process_dataset(dataset, user))

    @classmethod
    async def refresh_client_knowledge(cls, client_id: int) -> None:
        """
        Manually force reindexing of a client's dataset.
        """
        user = await cls._get_cognee_user()
        dataset = cls._dataset_name(client_id)
        logger.info(f"Reindexing dataset {dataset}")
        asyncio.create_task(cls._process_dataset(dataset, user))

    @classmethod
    async def save_client_message(cls, text: str, client_id: int) -> None:
        """
        Save a user message to the client's message dataset.
        """
        await cls.add_text(text, client_id=client_id, role=MessageRole.CLIENT)

    @classmethod
    async def save_ai_message(cls, text: str, client_id: int) -> None:
        """
        Save an AI message to the client's message dataset.
        """
        await cls.add_text(text, client_id=client_id, role=MessageRole.AI_COACH)

    @classmethod
    async def get_client_context(cls, client_id: int, query: str) -> dict[str, list[str]]:
        """
        Search client message dataset for relevant context.
        """
        user = await cls._get_cognee_user()
        await cls._ensure_profile_indexed(client_id, user)
        datasets = [cls._dataset_name(client_id), cls.GLOBAL_DATASET]
        try:
            messages = await cognee.search(query, datasets=datasets, top_k=5, user=user)
        except DatasetNotFoundError:
            messages = []
        except Exception as e:  # pragma: no cover - best effort
            logger.error(f"get_client_context failed: {e}")
            messages = []
        return {"messages": messages}
