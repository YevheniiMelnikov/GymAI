from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Optional, Tuple
import json
from uuid import uuid4

from core.ai_coach.cognee_config import CogneeConfig
from core.ai_coach.lock_cache import LockCache

import cognee
from cognee.modules.data.exceptions import DatasetNotFoundError
from cognee.modules.users.exceptions.exceptions import PermissionDeniedError
from cognee.modules.users.methods.get_default_user import get_default_user
from cognee.infrastructure.databases.exceptions import DatabaseNotCreatedError
from cognee.modules.engine.operations.setup import setup as cognee_setup
from loguru import logger

from config.app_settings import settings
from core.ai_coach.base import BaseAICoach
from core.ai_coach.knowledge_loader import KnowledgeLoader
from core.ai_coach.prompts import INITIAL_PROMPT, UPDATE_WORKOUT_PROMPT, SYSTEM_MESSAGE
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
