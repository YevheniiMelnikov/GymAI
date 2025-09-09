import asyncio
import os
from dataclasses import asdict, is_dataclass
from hashlib import sha256
from types import SimpleNamespace
from typing import Any

from loguru import logger

from ai_coach.agent.knowledge.base_knowledge_loader import KnowledgeLoader
from ai_coach.agent.knowledge.cognee_config import CogneeConfig
from ai_coach.agent.knowledge.utils.hash_store import HashStore
from ai_coach.agent.knowledge.utils.lock_cache import LockCache
from ai_coach.schemas import CogneeUser
from ai_coach.types import MessageRole
from core.exceptions import UserServiceError
from core.services import APIService
from core.schemas import Client

import cognee  # type: ignore

try:
    from cognee.modules.users.methods.get_default_user import get_default_user  # type: ignore
except Exception:

    async def get_default_user() -> Any | None:  # type: ignore
        return None


try:
    from cognee.modules.data.exceptions import DatasetNotFoundError  # type: ignore
    from cognee.modules.users.exceptions.exceptions import PermissionDeniedError  # type: ignore
except Exception:

    class DatasetNotFoundError(Exception): ...

    class PermissionDeniedError(Exception): ...


def _to_user_or_none(user: Any) -> Any | None:
    """Normalize user object into SimpleNamespace or return None."""
    if user is None:
        return None
    if isinstance(user, CogneeUser):
        return SimpleNamespace(**asdict(user))
    if is_dataclass(user):
        d = asdict(user)
        return SimpleNamespace(**d) if d.get("id") else None
    if getattr(user, "id", None):
        return user
    return None


class KnowledgeBase:
    """Cognee-backed knowledge storage for the coach agent."""

    _loader: KnowledgeLoader | None = None
    _cognify_locks: LockCache = LockCache()
    _user: Any | None = None

    GLOBAL_DATASET: str = os.environ.get("COGNEE_GLOBAL_DATASET", "external_docs")

    @classmethod
    async def initialize(cls, knowledge_loader: KnowledgeLoader | None = None) -> None:
        """Initialize Cognee config, user, and preload knowledge base."""
        CogneeConfig.apply()
        try:
            from cognee.modules.engine.operations.setup import setup as cognee_setup  # type: ignore

            await cognee_setup()
        except Exception:
            pass
        cls._loader = knowledge_loader
        cls._user = await cls._get_cognee_user()
        try:
            await cls.refresh()
        except Exception as e:
            logger.warning(f"Knowledge refresh skipped: {e}")

    @classmethod
    async def _get_cognee_user(cls) -> Any | None:
        """Fetch and cache default Cognee user."""
        if cls._user is not None:
            return cls._user
        try:
            cls._user = await get_default_user()
        except Exception:
            cls._user = None
        return cls._user

    @classmethod
    def _resolve_dataset_alias(cls, name: str) -> str:
        """Map dataset alias to actual dataset name (currently identity)."""
        return name

    @classmethod
    async def _ensure_dataset_exists(cls, name: str, user: Any | None) -> None:
        """Create dataset if it does not exist for the given user."""
        user_ns = _to_user_or_none(user)
        try:
            from cognee.modules.data.methods import (  # type: ignore
                get_authorized_dataset_by_name,
                create_authorized_dataset,
            )
        except Exception:
            return
        exists = await get_authorized_dataset_by_name(name, user_ns, "write")
        if exists is None:
            await create_authorized_dataset(name, user_ns)

    @classmethod
    async def refresh(cls) -> None:
        """Re-cognify global dataset and refresh loader if available."""
        user = await cls._get_cognee_user()
        ds = cls._resolve_dataset_alias(cls.GLOBAL_DATASET)
        await cls._ensure_dataset_exists(ds, user)
        if cls._loader:
            await cls._loader.refresh()
        try:
            await cognee.cognify(datasets=[ds], user=_to_user_or_none(user))
        except (PermissionDeniedError, DatasetNotFoundError) as e:
            logger.error(f"Knowledge base update skipped: {e}")

    @staticmethod
    def _dataset_name(client_id: int) -> str:
        """Generate dataset name for a client."""
        return f"client_{client_id}"

    @staticmethod
    def _client_profile_text(client: Client) -> str:
        """Format client profile attributes into text for indexing."""
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
    async def _ensure_profile_indexed(cls, client_id: int, user: Any | None) -> None:
        """Fetch client profile and add it to dataset if missing."""
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
    async def _process_dataset(cls, dataset: str, user: Any | None) -> None:
        """Run cognify on a dataset with a per-dataset lock."""
        lock = cls._cognify_locks.get(dataset)
        async with lock:
            ds = cls._resolve_dataset_alias(dataset)
            await cognee.cognify(datasets=[ds], user=_to_user_or_none(user))

    @classmethod
    async def update_dataset(
        cls,
        text: str,
        dataset: str,
        user: Any | None,
        node_set: list[str] | None = None,
    ) -> tuple[str, bool]:
        """Add text to dataset if new, update hash store, return (dataset, created)."""
        text = (text or "").strip()
        if not text:
            return dataset, False
        digest = sha256(text.encode()).hexdigest()
        ds_name = cls._resolve_dataset_alias(dataset)
        await cls._ensure_dataset_exists(ds_name, user)
        if await HashStore.contains(ds_name, digest):
            return ds_name, False
        try:
            info = await cognee.add(
                text,
                dataset_name=ds_name,
                user=_to_user_or_none(user),
                node_set=node_set,
            )
        except (DatasetNotFoundError, PermissionDeniedError):
            raise
        await HashStore.add(ds_name, digest)
        resolved = getattr(info, "dataset_id", None) or getattr(info, "dataset_name", None) or ds_name
        return str(resolved), True

    @classmethod
    async def search(cls, query: str, client_id: int, k: int | None = None) -> list[str]:
        """Search across client and global datasets."""
        user = await cls._get_cognee_user()
        await cls._ensure_profile_indexed(client_id, user)
        datasets = [cls._dataset_name(client_id), cls.GLOBAL_DATASET]
        datasets = [cls._resolve_dataset_alias(d) for d in datasets]
        try:
            params: dict[str, Any] = {
                "datasets": datasets,
                "user": _to_user_or_none(user),
            }
            if k is not None:
                params["top_k"] = k
            return await cognee.search(query, **params)
        except (PermissionDeniedError, DatasetNotFoundError) as e:
            logger.warning(f"Search issue client_id={client_id}: {e}")
        except Exception as e:
            logger.error(f"Unexpected search error client_id={client_id}: {e}")
        return []

    @classmethod
    async def add_text(
        cls,
        text: str,
        *,
        dataset: str | None = None,
        user: Any | None = None,
        node_set: list[str] | None = None,
        client_id: int | None = None,
        role: MessageRole | None = None,
    ) -> None:
        """Add message text to a dataset, schedule cognify if new."""
        user = await cls._get_cognee_user()
        ds = dataset or (cls._dataset_name(client_id) if client_id is not None else cls.GLOBAL_DATASET)
        if role:
            text = f"{role.value}: {text}"
        try:
            ds, created = await cls.update_dataset(text, ds, user, node_set=node_set or [])
            if created:
                asyncio.create_task(cls._process_dataset(ds, user))
        except PermissionDeniedError:
            raise
        except Exception:
            logger.warning("Add text skipped")

    @classmethod
    async def refresh_client_knowledge(cls, client_id: int) -> None:
        """Re-cognify client-specific dataset asynchronously."""
        user = await cls._get_cognee_user()
        dataset = cls._dataset_name(client_id)
        logger.info(f"Reindexing dataset {dataset}")
        asyncio.create_task(cls._process_dataset(dataset, user))

    @classmethod
    async def save_client_message(cls, text: str, client_id: int) -> None:
        """Save a client message into dataset."""
        await cls.add_text(text, client_id=client_id, role=MessageRole.CLIENT)

    @classmethod
    async def save_ai_message(cls, text: str, client_id: int) -> None:
        """Save an AI coach message into dataset."""
        await cls.add_text(text, client_id=client_id, role=MessageRole.AI_COACH)
