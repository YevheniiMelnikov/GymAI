from __future__ import annotations

import os
import sys
from typing import Optional
import asyncio

import cognee
from cognee import config

from config.env_settings import settings
from core.ai_coach.base import BaseAICoach

from core.ai_coach.knowledge_loader import KnowledgeLoader
from core.schemas import Client


class CogneeCoach(BaseAICoach):
    api_url = settings.COGNEE_API_URL
    api_key = settings.COGNEE_API_KEY
    model = settings.COGNEE_MODEL  # TODO: IMPLEMENT KNOWLEDGE BASE
    _configured = False
    _loader: Optional[KnowledgeLoader] = None

    @classmethod
    async def initialize(cls) -> None:
        cls._ensure_config()
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
        )
        await process.wait()
        await cognee.search("ping")

    @classmethod
    def set_loader(cls, loader: KnowledgeLoader) -> None:
        """Register a loader instance for fetching external knowledge."""
        cls._loader = loader

    @classmethod
    async def init_loader(cls, loader: KnowledgeLoader) -> None:
        """Register ``loader`` and load its data.

        This should be invoked once during startup, e.g. from ``bot/main.py``.
        """
        cls.set_loader(loader)
        await cls.load_external_knowledge()

    @classmethod
    def _ensure_config(cls) -> None:
        """Ensure Cognee is configured."""
        if cls._configured:
            return
        if cls.api_url:
            config.set_llm_endpoint(cls.api_url)
        if cls.api_key:
            config.set_llm_api_key(cls.api_key)
        if cls.model:
            config.set_llm_model(cls.model)
        config.set_vector_db_provider(settings.VECTORDATABASE_PROVIDER)
        config.set_vector_db_url(settings.VECTORDATABASE_URL)
        config.set_graph_database_provider(settings.GRAPH_DATABASE_PROVIDER)
        config.set_relational_db_config(
            {
                "db_host": settings.DB_HOST,
                "db_port": settings.DB_PORT,
                "db_username": settings.DB_USER,
                "db_password": settings.DB_PASSWORD,
                "db_name": settings.DB_NAME,
                "db_path": "",
                "db_provider": "postgres",
            }
        )
        cls._configured = True

    @staticmethod
    def _extract_client_data(client: Client) -> str:
        """Extract client data from the client object."""
        return ""

    @staticmethod
    def _make_initial_prompt(client_data: str) -> str:
        """Create the initial prompt based on the client data."""
        return ""  # TODO IMPLEMENT DB (CHAT MEMORY)

    @classmethod
    async def coach_request(cls, text: str) -> None:
        cls._ensure_config()
        await cognee.add(text)
        await cognee.cognify()
        await cognee.search(text)

    @classmethod
    async def load_external_knowledge(cls) -> None:
        cls._ensure_config()
        if cls._loader is None:
            return
        await cls._loader.load()
        await cls.update_knowledge_base()

    @classmethod
    async def update_knowledge_base(cls) -> None:
        cls._ensure_config()
        await cognee.cognify()

    @classmethod
    async def coach_assign(cls, client: Client) -> None:
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
        await cognee.cognify()

    @classmethod
    async def get_context(cls, chat_id: int, query: str) -> list:
        """Retrieve context for ``query`` from chat history."""
        cls._ensure_config()
        dataset = f"chat_{chat_id}"
        return await cognee.search(query, datasets=[dataset], top_k=5)
