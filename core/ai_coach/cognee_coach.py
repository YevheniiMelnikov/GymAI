from __future__ import annotations

import os
import sys
import asyncio
import warnings
import logging
from dataclasses import dataclass
from typing import Optional, Any
from pathlib import Path
from uuid import uuid4

from sqlalchemy.exc import SAWarning
from loguru import logger

from config.logger import configure_loguru
from config.env_settings import settings
from core.ai_coach.base import BaseAICoach
from core.ai_coach.knowledge_loader import KnowledgeLoader
from core.schemas import Client

# ────────────────────────── boilerplate ──────────────────────────
default_prompt = os.environ.get("GRAPH_PROMPT_PATH", "./core/ai_coach/global_system_prompt.txt")
os.environ["GRAPH_PROMPT_PATH"] = Path(default_prompt).resolve().as_posix()

warnings.filterwarnings("ignore", category=SAWarning)
logging.getLogger("langfuse").setLevel(logging.ERROR)

import cognee  # noqa: E402
from cognee.modules.data.exceptions import DatasetNotFoundError  # noqa: E402
from cognee.modules.users.exceptions.exceptions import PermissionDeniedError  # noqa: E402
from cognee.modules.users.methods.get_default_user import get_default_user  # noqa: E402

os.environ.setdefault("LITELLM_LOG", "WARNING")
os.environ.setdefault("LOG_LEVEL", "WARNING")

LANGUAGE_NAMES = {"ua": "Ukrainian", "ru": "Russian", "eng": "English"}

configure_loguru()
logger.level("COGNEE", no=15, color="<cyan>")
logging.getLogger("cognee").setLevel(logging.INFO)


# ─────────────────────────── util helper ─────────────────────────
async def _safe_add(text: str, dataset: str, user) -> tuple[str, bool]:
    """Возвращает (dataset_id, created_now). При 403 создаём новый датасет."""
    logger.debug(f"safe_add → dataset={dataset!r}")
    if not text.strip():
        return dataset, False
    try:
        info = await cognee.add(text, dataset_name=dataset, user=user)
        return getattr(info, "dataset_id", dataset), True
    except PermissionDeniedError:
        new_name = f"{dataset}_{uuid4().hex[:8]}"
        logger.debug(f"403 on {dataset}, retrying as {new_name}")
        info = await cognee.add(text, dataset_name=new_name, user=user)
        return getattr(info, "dataset_id", new_name), True


# ────────────────────────── config dataclass ─────────────────────
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

        p = Path(self.graph_prompt_path).resolve().as_posix()
        os.environ["GRAPH_PROMPT_PATH"] = p
        cognee.config.set_llm_config({"graph_prompt_path": p})

        cognee.config.set_relational_db_config(
            dict(
                db_host=self.db_host,
                db_port=self.db_port,
                db_username=self.db_user,
                db_password=self.db_password,
                db_name=self.db_name,
                db_path="",
                db_provider="postgres",
            )
        )


# ───────────────────────────── main class ────────────────────────
class CogneeCoach(BaseAICoach):
    _configured = False
    _loader: Optional[KnowledgeLoader] = None
    _cognify_locks: dict[str, asyncio.Lock] = {}
    _user: Optional[Any] = None

    # ---------- bootstrap ----------
    @classmethod
    async def initialize(cls) -> None:
        cls._ensure_config()
        if cls._user is None:
            cls._user = await get_default_user()
            logger.debug(f"Cognee default user: {cls._user.id}")

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
        except Exception as e:
            logger.warning(f"Cognee ping failed: {e}")
        logger.success("AI coach successfully configured")

    @classmethod
    async def init_loader(cls, loader: KnowledgeLoader) -> None:
        cls.set_loader(loader)
        await cls.refresh_knowledge_base()

    @classmethod
    def set_loader(cls, loader: KnowledgeLoader) -> None:
        cls._loader = loader

    @classmethod
    def _ensure_config(cls) -> None:
        if cls._configured:
            return
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

    # ---------- internal helpers ----------
    @classmethod
    async def _cognify_dataset(cls, dataset_id: str, user) -> None:
        lock = cls._cognify_locks.setdefault(dataset_id, asyncio.Lock())
        async with lock:
            await cognee.cognify(datasets=[dataset_id], user=user)

    # ---------- prompt helpers ----------
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
        return "; ".join(f"{k}: {v}" for k, v in details.items() if v)

    @staticmethod
    def _make_initial_prompt(client_data: str) -> str:
        return (
            "Memorize the following client profile information and use it as "
            "context for all future responses.\n" + client_data
        )

    # ---------- dataset/context ----------
    @classmethod
    async def get_context(cls, chat_id: int, query: str) -> list:
        """Создаём (или переименовываем) датасет и ищем уже по итоговому id."""
        cls._ensure_config()
        if cls._user is None:
            await cls.initialize()
        user = cls._user
        base_name = f"chat_{chat_id}_{user.id}"
        try:
            ds_id, _ = await _safe_add("init", base_name, user)  # ensure exists / own
            return await cognee.search(query, datasets=[ds_id], top_k=5, user=user)
        except Exception as e:
            logger.error(f"get_context failed: {e}")
            return []

    # ---------- main entry ----------
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

        parts: list[str] = []
        if client:
            cd = cls._extract_client_data(client)
            if cd:
                parts.append(f"Client info: {cd}")
            try:
                from core.cache import Cache

                prg = await Cache.workout.get_program(client.profile, use_fallback=False)
                parts.append(f"Latest program: {prg.workout_type}, split {prg.split_number}")
                sub = await Cache.workout.get_latest_subscription(client.profile, use_fallback=False)
                parts.append(f"Active subscription: {sub.workout_type} {sub.workout_days} period {sub.period}")
            except Exception:
                pass

        if chat_id:
            try:
                hist = await cls.get_context(chat_id, text)
                if hist:
                    parts.append("\n".join(hist))
            except Exception:
                pass

        parts.append(text)
        if language:
            parts.append(f"Answer in {LANGUAGE_NAMES.get(language, language)}.")
        final_prompt = "\n".join(parts)

        base = "main_dataset" if client is None else f"main_dataset_{client.id}"
        if cls._user is None:
            await cls.initialize()
        user = cls._user
        dataset = f"{base}_{user.id}"
        logger.debug(f"Adding prompt to dataset {dataset}: {final_prompt[:100]}")

        try:
            ds_id, created = await _safe_add(final_prompt, dataset, user)
            if created:
                asyncio.create_task(cls._cognify_dataset(ds_id, user))
        except PermissionDeniedError as e:
            logger.error(f"Permission denied while adding data: {e}")
            return []
        except Exception as e:
            logger.error(f"Failed to add data to dataset: {e}")
            return []

        try:
            return await cognee.search(final_prompt, datasets=[ds_id], user=user)
        except DatasetNotFoundError:
            logger.error("Search failed, dataset not found")
        except PermissionDeniedError as e:
            logger.error(f"Permission denied during search: {e}")
        return []

    # ---------- knowledge base ----------
    @classmethod
    async def refresh_knowledge_base(cls) -> None:
        cls._ensure_config()
        if cls._loader:
            await cls._loader.refresh()
            await cls.update_knowledge_base()

    @classmethod
    async def update_knowledge_base(cls) -> None:
        cls._ensure_config()
        try:
            await cognee.cognify()
        except DatasetNotFoundError:
            logger.warning("No datasets found to process")
        except PermissionDeniedError as e:
            logger.error(f"Permission denied while updating knowledge base: {e}")

    # ---------- misc helpers ----------
    @classmethod
    async def assign_client(cls, client: Client) -> None:
        prompt = cls._make_initial_prompt(cls._extract_client_data(client))
        await cls.coach_request(prompt)

    @classmethod
    async def save_user_message(cls, text: str, chat_id: int, client_id: int) -> None:
        if not text.strip():
            return
        cls._ensure_config()
        if cls._user is None:
            await cls.initialize()
        user = cls._user
        ds_id, created = await _safe_add(text, f"chat_{chat_id}_{user.id}", user)
        if created:
            asyncio.create_task(cls._cognify_dataset(ds_id, user))

    # ---------- workout update ----------
    @classmethod
    async def process_workout_result(
        cls,
        client_id: int,
        feedback: str,
        language: str | None = None,
    ) -> str:
        cls._ensure_config()
        try:
            ctx = await cls.get_context(client_id, "workout")
        except Exception:
            ctx = []
        prompt = "\n".join([feedback, *ctx, "Update the workout plan accordingly."])
        resp = await cls.coach_request(prompt, chat_id=client_id, language=language)
        return resp[0] if resp else ""
