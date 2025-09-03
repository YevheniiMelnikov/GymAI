from __future__ import annotations

import asyncio
import os
import traceback
from dataclasses import asdict, dataclass, is_dataclass
from hashlib import sha256
from types import SimpleNamespace
from typing import Any, Optional, Tuple

from loguru import logger

from ai_coach.base_coach import BaseAICoach
from ai_coach.base_knowledge_loader import KnowledgeLoader
from ai_coach.cognee_config import CogneeConfig
from ai_coach.hash_store import HashStore
from ai_coach.lock_cache import LockCache
from ai_coach.schemas import MessageRole
from core.exceptions import UserServiceError
from core.services import APIService
from core.schemas import Client

import cognee  # type: ignore

try:
    from cognee.modules.users.methods.get_default_user import get_default_user  # type: ignore
except Exception:  # pragma: no cover - fallback

    async def get_default_user() -> Any | None:  # type: ignore
        return None


def _c():
    return cognee


def _exceptions():
    from cognee.modules.data.exceptions import DatasetNotFoundError  # type: ignore
    from cognee.modules.users.exceptions.exceptions import PermissionDeniedError  # type: ignore

    return DatasetNotFoundError, PermissionDeniedError


DatasetNotFoundError, PermissionDeniedError = _exceptions()


@dataclass
class CoachUser:
    id: Any
    tenant_id: Any | None = None
    roles: list[str] | None = None


def _debug_enabled() -> bool:
    return os.environ.get("COGNEE_DEBUG", "0") == "1"


def _to_user_or_none(u: Any) -> Any | None:
    if u is None:
        return None
    if isinstance(u, CoachUser):
        d = asdict(u)
        return SimpleNamespace(**d)
    if is_dataclass(u):
        d = asdict(u)
        idv = d.get("id")
        return SimpleNamespace(**({**d} if idv else d)) if idv else None
    if hasattr(u, "id") and getattr(u, "id", None):
        return u
    return None


def _brief(obj: Any, limit: int = 200) -> str:
    try:
        s = repr(obj)
    except Exception:
        s = f"<{type(obj).__name__}>"
    return (s[:limit] + "…") if len(s) > limit else s


async def _safe_add(*, text: str, dataset_name: str, user: Any | None, node_set: list[str] | None):
    user = _to_user_or_none(user)
    try:
        res = await _c().add(text, dataset_name=dataset_name, user=user, node_set=node_set)
        if _debug_enabled():
            logger.debug(
                "[COGNEE_DEBUG] add() OK dataset=%s user=%s node_set=%s -> %s",
                dataset_name,
                getattr(user, "id", None) if user is not None else None,
                node_set,
                _brief(res),
            )
        return res
    except Exception as e:
        logger.error(
            "[COGNEE_DEBUG] add() FAIL dataset=%s user=%s node_set=%s exc=%s\n%s",
            dataset_name,
            _brief(user),
            node_set,
            e,
            traceback.format_exc(),
        )
        raise


async def _safe_cognify(*, datasets: list[str] | None, user: Any | None):
    user = _to_user_or_none(user)
    try:
        res = await _c().cognify(datasets=datasets, user=user)
        if _debug_enabled():
            logger.debug(
                "[COGNEE_DEBUG] cognify() OK datasets=%s user=%s -> %s",
                datasets,
                getattr(user, "id", None) if user is not None else None,
                _brief(res),
            )
        return res
    except Exception as e:
        logger.error(
            "[COGNEE_DEBUG] cognify() FAIL datasets=%s user=%s exc=%s\n%s",
            datasets,
            _brief(user),
            e,
            traceback.format_exc(),
        )
        raise


class CogneeCoach(BaseAICoach):
    _loader: Optional[KnowledgeLoader] = None
    _cognify_locks: LockCache = LockCache()
    _user: Optional[Any] = None

    GLOBAL_DATASET: str = os.environ.get("COGNEE_GLOBAL_DATASET", "external_docs")

    @classmethod
    async def initialize(cls, knowledge_loader: KnowledgeLoader | None = None) -> None:
        CogneeConfig.apply()
        try:
            from cognee.modules.engine.operations.setup import setup as cognee_setup  # type: ignore

            await cognee_setup()
        except Exception as e:
            logger.debug(f"Cognee setup note: {e}")

        cls._loader = knowledge_loader
        cls._user = await cls._get_cognee_user()

        try:
            await cls.refresh_knowledge_base()
        except Exception as e:
            logger.warning(f"Knowledge refresh (non-fatal): {e}")

        logger.debug("CogneeCoach: initialize complete")

    @classmethod
    async def _get_cognee_user(cls) -> Any | None:
        if cls._user is not None:
            return cls._user
        try:
            cls._user = await get_default_user()
        except Exception as e:  # pragma: no cover - best effort
            if _debug_enabled():
                logger.debug("[COGNEE_DEBUG] get_default_user failed: %s", e)
            cls._user = None
        return cls._user

    @classmethod
    def _resolve_dataset_alias(cls, name: str) -> str:
        return name

    @classmethod
    async def refresh_knowledge_base(cls) -> None:
        DatasetNotFoundError, PermissionDeniedError = _exceptions()
        if cls._loader:
            await cls._loader.refresh()
        user = await cls._get_cognee_user()
        try:
            ds = cls._resolve_dataset_alias(cls.GLOBAL_DATASET)
            await _safe_cognify(datasets=[ds], user=user)
        except (PermissionDeniedError, DatasetNotFoundError) as e:
            logger.error(f"Knowledge base update skipped: {e}")

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
    async def _ensure_profile_indexed(cls, client_id: int, user: Any | None) -> None:
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
        lock = cls._cognify_locks.get(dataset)
        async with lock:
            ds = cls._resolve_dataset_alias(dataset)
            await _safe_cognify(datasets=[ds], user=user)

    @classmethod
    async def update_dataset(
        cls,
        text: str,
        dataset: str,
        user: Any | None,
        node_set: list[str] | None = None,
    ) -> Tuple[str, bool]:
        text = (text or "").strip()
        if not text:
            return dataset, False
        digest = sha256(text.encode()).hexdigest()
        ds_name = cls._resolve_dataset_alias(dataset)
        if await HashStore.contains(ds_name, digest):
            if _debug_enabled():
                logger.debug("[COGNEE_DEBUG] HashStore hit dataset=%s digest=%s (skip add)", ds_name, digest[:12])
            return ds_name, False
        try:
            info = await _safe_add(text=text, dataset_name=ds_name, user=user, node_set=node_set)
        except (DatasetNotFoundError, PermissionDeniedError):
            raise
        await HashStore.add(ds_name, digest)
        resolved = getattr(info, "dataset_id", None) or getattr(info, "dataset_name", None) or ds_name
        return str(resolved), True

    @classmethod
    async def make_request(cls, prompt: str, client_id: int) -> list[str]:
        DatasetNotFoundError, PermissionDeniedError = _exceptions()
        user = await cls._get_cognee_user()
        await cls._ensure_profile_indexed(client_id, user)
        datasets = [cls._dataset_name(client_id), cls.GLOBAL_DATASET]
        datasets = [cls._resolve_dataset_alias(d) for d in datasets]
        try:
            return await _c().search(prompt, datasets=datasets, user=user)
        except (PermissionDeniedError, DatasetNotFoundError) as e:
            logger.warning(f"Search issue for client {client_id}: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error during client {client_id} request: {e}")
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
            logger.opt(exception=True).warning("Add text skipped")

    @classmethod
    async def refresh_client_knowledge(cls, client_id: int) -> None:
        user = await cls._get_cognee_user()
        dataset = cls._dataset_name(client_id)
        logger.info(f"Reindexing dataset {dataset}")
        asyncio.create_task(cls._process_dataset(dataset, user))

    @classmethod
    async def save_client_message(cls, text: str, client_id: int) -> None:
        await cls.add_text(text, client_id=client_id, role=MessageRole.CLIENT)

    @classmethod
    async def save_ai_message(cls, text: str, client_id: int) -> None:
        await cls.add_text(text, client_id=client_id, role=MessageRole.AI_COACH)

    @classmethod
    async def get_client_context(cls, client_id: int, query: str) -> dict[str, list[str]]:
        DatasetNotFoundError, _ = _exceptions()
        user = await cls._get_cognee_user()
        await cls._ensure_profile_indexed(client_id, user)
        datasets = [cls._dataset_name(client_id), cls.GLOBAL_DATASET]
        datasets = [cls._resolve_dataset_alias(d) for d in datasets]
        try:
            messages = await _c().search(query, datasets=datasets, top_k=5, user=user)
        except DatasetNotFoundError:
            messages = []
        except Exception as e:
            logger.error(f"get_client_context failed: {e}")
            messages = []
        return {"messages": messages}
