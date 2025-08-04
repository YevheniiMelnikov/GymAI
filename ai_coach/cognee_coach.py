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

    _configured: bool = False
    _loader: Optional[KnowledgeLoader] = None
    _cognify_locks: LockCache = LockCache()
    _user: Optional[Any] = None

    @classmethod
    async def initialize(cls, knowledge_loader: KnowledgeLoader | None = None) -> None:
        """
        Initialize Cognee configuration, apply DB migrations and test connectivity.
        """
        cls._ensure_config()
        cls._loader = knowledge_loader
        await cls.refresh_knowledge_base()
        await cls._get_user()

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
    def _ensure_config(cls) -> None:
        """Apply Cognee configuration once."""
        if not cls._configured:
            CogneeConfig.apply()
            cls._configured = True

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

    @classmethod
    async def _get_user(cls) -> Any:
        """Retrieve and cache the default Cognee user."""
        if cls._user is None:
            try:
                cls._user = await get_default_user()
            except DatabaseNotCreatedError:
                await cognee_setup()
                cls._user = await get_default_user()
        return cls._user

    @staticmethod
    async def _safe_add(text: str, dataset: str, user: Any) -> Tuple[str, bool]:
        """
        Add text to dataset if not already present.
        Returns (dataset_id, was_created).
        """
        logger.trace(f"_safe_add → dataset={dataset!r}")
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
    async def _cognify_dataset(cls, dataset_id: str, user: Any) -> None:
        """Trigger index update for a dataset, with locking."""
        lock = cls._cognify_locks.get(dataset_id)
        async with lock:
            await cognee.cognify(datasets=[dataset_id], user=user)

    @classmethod
    async def update_client_knowledge(
        cls,
        text: str,
        client_id: int,
        *,
        kind: DataKind = DataKind.MESSAGE,
        role: MessageRole | None = None,
    ) -> None:
        """Persist a text entry to the client's dataset and trigger cognify."""
        cls._ensure_config()
        user = await cls._get_user()
        ds_name = f"client_{client_id}_{kind.value}"
        if kind is DataKind.MESSAGE:
            if role is None:
                raise ValueError("role is required for message entries")
            text = f"{role.value}: {text}"
        ds_id, created = await cls._safe_add(text, ds_name, user)
        if created:
            asyncio.create_task(cls._cognify_dataset(ds_id, user))

    @classmethod
    async def get_context(cls, client_id: int, query: str) -> list[str]:
        """Search client's message dataset for relevant context."""
        cls._ensure_config()
        user = await cls._get_user()
        ds_name = f"client_{client_id}_message"
        try:
            return await cognee.search(query, datasets=[ds_name], top_k=5, user=user)
        except DatasetNotFoundError:
            return []
        except Exception as e:  # pragma: no cover - best effort
            logger.error(f"get_context failed: {e}")
            return []

    @classmethod
    async def make_request(cls, prompt: str, client_id: int) -> list[str]:
        """Search a client's prompt dataset without modifying it."""
        cls._ensure_config()
        user = await cls._get_user()
        ds_name = f"client_{client_id}_prompt"

        try:
            return await cognee.search(prompt, datasets=[ds_name], user=user)
        except (PermissionDeniedError, DatasetNotFoundError) as e:
            logger.warning(f"Search issue for client {client_id}: {e}")
        except Exception as e:  # pragma: no cover - best effort
            logger.exception(
                f"Unexpected error during client {client_id} request: {e}"
            )
        return []

    @classmethod
    async def reindex(
        cls, client_id: int, kind: DataKind = DataKind.MESSAGE
    ) -> None:
        """Force reindex of a client's dataset."""
        cls._ensure_config()
        user = await cls._get_user()
        ds_name = f"client_{client_id}_{kind.value}"
        logger.info(f"Reindexing dataset {ds_name}")
        await cls._cognify_dataset(ds_name, user)
