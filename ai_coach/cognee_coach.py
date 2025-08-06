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
from ai_coach.enums import DataKind, MessageRole
from ai_coach.utils.lock_cache import LockCache
from ai_coach.utils.hash_store import HashStore
from config.app_settings import settings


class CogneeCoach(BaseAICoach):
    """
    AI Coach implementation using Cognee for context, memory, and knowledge management.
    """

    _loader: Optional[KnowledgeLoader] = None
    _cognify_locks: LockCache = LockCache()
    _user: Optional[Any] = None

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
        Perform a search in the client's prompt dataset without modifying or reindexing it.
        """
        user = await cls._get_cognee_user()
        ds_name = cls._dataset_name(client_id, DataKind.PROMPT)

        try:
            return await cognee.search(prompt, datasets=[ds_name], user=user)
        except (PermissionDeniedError, DatasetNotFoundError) as e:
            logger.warning(f"Search issue for client {client_id}: {e}")
        except Exception as e:  # pragma: no cover - best effort
            logger.exception(
                f"Unexpected error during client {client_id} request: {e}"
            )
        return []

    @staticmethod
    async def update_dataset(text: str, dataset: str, user: Any) -> Tuple[str, bool]:
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

        info = await cognee.add(text, dataset_name=dataset, user=user)
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
    def _dataset_name(client_id: int, kind: DataKind) -> str:
        return f"client_{client_id}_{kind.value}"

    @classmethod
    async def _update_client_knowledge(
        cls,
        text: str,
        client_id: int,
        *,
        data_kind: DataKind = DataKind.MESSAGE,
        role: MessageRole | None = None,
    ) -> None:
        """
        Persist a text entry to the client's dataset and trigger indexing if new.
        """
        user = await cls._get_cognee_user()
        ds_name = cls._dataset_name(client_id, data_kind)
        if data_kind is DataKind.MESSAGE:
            if role is None:
                raise ValueError("role is required for message entries")
            text = f"{role.value}: {text}"
        dataset, created = await cls.update_dataset(text, ds_name, user)
        if created:
            asyncio.create_task(cls._process_dataset(dataset, user))

    @classmethod
    async def refresh_client_knowledge(cls, client_id: int, data_kind: Any = None) -> None:
        """
        Manually force reindexing of a client's dataset.
        """
        data_kind = data_kind or DataKind.PROMPT
        user = await cls._get_cognee_user()
        dataset = cls._dataset_name(client_id, data_kind)
        logger.info(f"Reindexing dataset {dataset}")
        asyncio.create_task(cls._process_dataset(dataset, user))

    @classmethod
    async def save_client_message(cls, text: str, client_id: int) -> None:
        """
        Save a user message to the client's message dataset.
        """
        await cls._update_client_knowledge(
            text, client_id, data_kind=DataKind.MESSAGE, role=MessageRole.CLIENT
        )

    @classmethod
    async def save_ai_message(cls, text: str, client_id: int) -> None:
        """
        Save an AI message to the client's message dataset.
        """
        await cls._update_client_knowledge(
            text, client_id, data_kind=DataKind.MESSAGE, role=MessageRole.AI_COACH
        )

    @classmethod
    async def save_prompt(cls, text: str, client_id: int) -> None:
        """
        Save a prompt to the client's prompt dataset.
        """
        await cls._update_client_knowledge(text, client_id, data_kind=DataKind.PROMPT)

    @classmethod
    async def get_client_context(
        cls, client_id: int, query: str
    ) -> dict[str, list[str]]:
        """
        Search client datasets (message and prompt) for relevant context.
        """
        user = await cls._get_cognee_user()
        datasets = {
            "messages": cls._dataset_name(client_id, DataKind.MESSAGE),
            "prompts": cls._dataset_name(client_id, DataKind.PROMPT),
        }
        results: dict[str, list[str]] = {}

        for kind, ds_name in datasets.items():
            try:
                results[kind] = await cognee.search(query, datasets=[ds_name], top_k=5, user=user)
            except DatasetNotFoundError:
                results[kind] = []
            except Exception as e:  # pragma: no cover - best effort
                logger.error(f"get_client_context failed on {kind}: {e}")
                results[kind] = []

        return results
