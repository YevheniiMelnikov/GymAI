from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Optional, Tuple
from hashlib import sha256

from ai_coach.cognee_config import CogneeConfig
from ai_coach.utils.lock_cache import LockCache
from ai_coach.utils.hash_store import HashStore

import cognee
from cognee.modules.data.exceptions import DatasetNotFoundError
from cognee.modules.users.exceptions.exceptions import PermissionDeniedError
from cognee.modules.users.methods.get_default_user import get_default_user
from cognee.infrastructure.databases.exceptions import DatabaseNotCreatedError
from cognee.modules.engine.operations.setup import setup as cognee_setup
from loguru import logger

from config.app_settings import settings
from ai_coach.base_coach import BaseAICoach
from ai_coach.base_knowledge_loader import KnowledgeLoader
from core.schemas import Client


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
    def _ensure_config(cls) -> None:
        """Apply Cognee configuration only once."""
        if not cls._configured:
            CogneeConfig.apply()
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

    @staticmethod
    async def _safe_add(text: str, dataset: str, user: Any) -> Tuple[str, bool]:
        """Add text to dataset if not already present."""
        logger.trace(f"_safe_add → dataset={dataset!r}")
        if not text.strip():
            return dataset, False

        digest = sha256(text.encode()).hexdigest()
        if await HashStore.contains(dataset, digest):
            return dataset, False

        info = await cognee.add(text, dataset_name=dataset, user=user)
        await HashStore.add(dataset, digest)
        return getattr(info, "dataset_id", dataset), True

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
    async def save_prompt(cls, text: str, *, client: Client) -> None:
        """Persist an AI prompt or response in the client's dataset."""
        if not text.strip():
            return
        cls._ensure_config()
        user = await cls._get_user()
        ds_name = str(client.id)
        await cls._add_and_cognify(text, ds_name, user)

    @classmethod
    async def get_context(cls, client_id: int, query: str) -> list[str]:
        """Search client history for relevant context."""
        cls._ensure_config()
        user = await cls._get_user()
        ds_name = str(client_id)
        try:
            return await cognee.search(query, datasets=[ds_name], top_k=5, user=user)
        except DatasetNotFoundError:
            return []
        except Exception as e:
            logger.error(f"get_context failed: {e}")
            return []

    @classmethod
    async def make_request(cls, prompt: str, *, client: Client) -> list[str]:
        """Reindex and search an existing client dataset without modifying it."""
        cls._ensure_config()
        user = await cls._get_user()
        ds_name = str(client.id)

        try:
            await cls.reindex(client)
            return await cognee.search(prompt, datasets=[ds_name], user=user)
        except PermissionDeniedError as e:
            logger.error(f"Permission denied: {e}")
        except DatasetNotFoundError:
            logger.error("Search failed: dataset not found")
        except Exception as e:
            logger.error(
                f"Unexpected AI coach error during client {client.id} request: {e}"
            )
        return []

    @classmethod
    async def save_user_message(cls, text: str, client_id: int) -> None:
        """Store a raw user message into the client's dataset."""
        if not text.strip():
            return
        cls._ensure_config()
        user = await cls._get_user()
        ds_name = str(client_id)
        await cls._add_and_cognify(text, ds_name, user)

    @classmethod
    async def reindex(cls, client: Client) -> None:
        """Force re-cognify of a client's dataset."""
        cls._ensure_config()
        user = await cls._get_user()
        ds_name = str(client.id)
        logger.info(f"Reindexing dataset {ds_name}")
        await cls._cognify_dataset(ds_name, user)
