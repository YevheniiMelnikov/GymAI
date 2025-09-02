from __future__ import annotations

import asyncio
import importlib
import os
import sys
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
from config.app_settings import settings
from core.exceptions import UserServiceError
from core.services import APIService
from core.schemas import Client


def _c():
    import cognee  # type: ignore

    return cognee


def _get_default_user():
    from cognee.modules.users.methods.get_default_user import get_default_user  # type: ignore

    return get_default_user


def _cognee_setup():
    from cognee.modules.engine.operations.setup import setup as cognee_setup  # type: ignore

    return cognee_setup


def _exceptions():
    from cognee.modules.data.exceptions import DatasetNotFoundError  # type: ignore
    from cognee.modules.users.exceptions.exceptions import PermissionDeniedError  # type: ignore

    return DatasetNotFoundError, PermissionDeniedError


def _load_or_create_func():
    try:
        mod = importlib.import_module("cognee.modules.data.methods.load_or_create_datasets")  # type: ignore
        func = getattr(mod, "load_or_create_datasets", None)
        return func if callable(func) else None
    except Exception:
        return None


@dataclass
class CoachUser:
    id: str


def _debug_enabled() -> bool:
    return os.getenv("COGNEE_DEBUG", "0") not in ("0", "", "false", "False")


def _to_user_with_id(u: Any) -> Any:
    if u is None:
        return SimpleNamespace(id="default")
    if isinstance(u, CoachUser):
        return SimpleNamespace(**asdict(u))
    if is_dataclass(u):
        d = asdict(u)
        return SimpleNamespace(id=d.get("id") or "default", **d)
    if hasattr(u, "id") and getattr(u, "id", None):
        return u
    try:
        return SimpleNamespace(id=str(u))
    except Exception:
        return SimpleNamespace(id="default")


def _brief(obj: Any, limit: int = 200) -> str:
    try:
        s = repr(obj)
    except Exception:
        s = f"<{type(obj).__name__}>"
    return (s[:limit] + "…") if len(s) > limit else s


async def _safe_add(*, text: str, dataset_name: str, user: Any, node_set: list[str] | None):
    user = _to_user_with_id(user)
    try:
        res = await _c().add(text, dataset_name=dataset_name, user=user, node_set=node_set)
        if _debug_enabled():
            logger.debug(
                "[COGNEE_DEBUG] add() OK dataset=%s user.id=%s node_set=%s -> %s",
                dataset_name,
                getattr(user, "id", None),
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


async def _safe_cognify(*, datasets: list[str] | None, user: Any):
    user = _to_user_with_id(user)
    try:
        res = await _c().cognify(datasets=datasets, user=user)
        if _debug_enabled():
            logger.debug(
                "[COGNEE_DEBUG] cognify() OK datasets=%s user.id=%s -> %s",
                datasets,
                getattr(user, "id", None),
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

    GLOBAL_DATASET: str = "external_docs"

    @classmethod
    async def initialize(cls, knowledge_loader: KnowledgeLoader | None = None) -> None:
        CogneeConfig.apply()

        try:
            await _cognee_setup()()
        except Exception as e:
            logger.debug(f"Cognee setup note: {e}")

        cls._loader = knowledge_loader
        cls._user = await cls._get_cognee_user()

        try:
            await cls.refresh_knowledge_base()
        except Exception as e:
            logger.warning(f"Knowledge refresh (non-fatal): {e}")

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

        if _debug_enabled():
            await cls._deep_probe_rbac()

        logger.debug("CogneeCoach: initialize complete")

    @classmethod
    async def _get_cognee_user(cls) -> Any:
        if cls._user is not None and getattr(cls._user, "id", None):
            return cls._user

        get_default_user = _get_default_user()
        try:
            user = await get_default_user()
            if user and getattr(user, "id", None):
                cls._user = user
                return cls._user
        except Exception:
            try:
                await _cognee_setup()()
                user = await get_default_user()
                if user and getattr(user, "id", None):
                    cls._user = user
                    return cls._user
            except Exception:
                pass

        cls._user = CoachUser(id="default")
        return cls._user

    @classmethod
    async def _ensure_dataset_exists(cls, dataset: str, user: Any) -> None:
        user = _to_user_with_id(user)

        try:
            func = _load_or_create_func()
            if callable(func):
                await func([dataset], [], user)
                if _debug_enabled():
                    logger.debug("[COGNEE_DEBUG] ensure_dataset_exists(%s) via load_or_create_datasets()", dataset)
                return
        except Exception as e:
            logger.debug(f"ensure_dataset_exists note via load_or_create_datasets: {e}")

        try:
            mod = importlib.import_module("cognee.modules.pipelines.layers.resolve_authorized_user_datasets")  # type: ignore
            resolve_many = getattr(mod, "resolve_authorized_user_datasets", None)
            if callable(resolve_many):
                _user_out, _authorized = await resolve_many([dataset], user)
                if _debug_enabled():
                    logger.debug(
                        "[COGNEE_DEBUG] ensure_dataset_exists(%s) via resolve_authorized_user_datasets()", dataset
                    )
                return
        except Exception as e:
            logger.debug(f"ensure_dataset_exists note via resolve_authorized_user_datasets: {e}")

        logger.debug("ensure_dataset_exists: no creation path succeeded for %r (will rely on add/cognify)", dataset)

    @classmethod
    async def _deep_probe_rbac(cls) -> None:
        user = _to_user_with_id(await cls._get_cognee_user())
        try:
            from cognee.modules.users.permissions.methods.get_all_user_permission_datasets import (  # type: ignore
                get_all_user_permission_datasets,
            )

            lst = await get_all_user_permission_datasets(user, "read")
            bad = [x for x in (lst or []) if not hasattr(x, "id")]
            logger.debug(
                "[COGNEE_DEBUG] get_all_user_permission_datasets(%s) -> %d items, bad=%d %s",
                getattr(user, "id", None),
                len(lst or []),
                len(bad),
                _brief(bad),
            )
        except Exception as e:
            logger.error(
                "[COGNEE_DEBUG] probe get_all_user_permission_datasets failed: %s\n%s", e, traceback.format_exc()
            )

        try:
            from cognee.modules.data.methods.get_authorized_existing_datasets import (  # type: ignore
                get_authorized_existing_datasets,
            )

            lst = await get_authorized_existing_datasets(["__health__"], "read", user)
            bad = [x for x in (lst or []) if not hasattr(x, "id")]
            logger.debug(
                "[COGNEE_DEBUG] get_authorized_existing_datasets(['__health__']) -> %d items, bad=%d %s",
                len(lst or []),
                len(bad),
                _brief(bad),
            )
        except Exception as e:
            logger.error(
                "[COGNEE_DEBUG] probe get_authorized_existing_datasets failed: %s\n%s", e, traceback.format_exc()
            )

        try:
            from cognee.modules.pipelines.layers.resolve_authorized_user_dataset import (  # type: ignore
                resolve_authorized_user_dataset,
            )

            u2, ds = await resolve_authorized_user_dataset(None, "__health__", user)
            logger.debug(
                "[COGNEE_DEBUG] resolve_authorized_user_dataset(None,'__health__') -> user.id=%s dataset=%s",
                getattr(u2, "id", None),
                _brief(ds),
            )
        except Exception as e:
            logger.error(
                "[COGNEE_DEBUG] probe resolve_authorized_user_dataset failed: %s\n%s", e, traceback.format_exc()
            )

    @classmethod
    async def refresh_knowledge_base(cls) -> None:
        DatasetNotFoundError, PermissionDeniedError = _exceptions()
        if cls._loader:
            await cls._loader.refresh()
        try:
            user = await cls._get_cognee_user()
            await cls._ensure_dataset_exists(cls.GLOBAL_DATASET, user)
            await _safe_cognify(datasets=None, user=user)
        except DatasetNotFoundError:
            pass
        except PermissionDeniedError as e:
            logger.error(f"Permission denied while updating knowledge base: {e}")

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

        await cls._ensure_dataset_exists(dataset, user)

        dataset, created = await cls.update_dataset(text, dataset, user, node_set=["client_profile"])
        if created:
            await cls._process_dataset(dataset, user)

    @classmethod
    async def _process_dataset(cls, dataset: str, user: Any) -> None:
        lock = cls._cognify_locks.get(dataset)
        async with lock:
            await _safe_cognify(datasets=[dataset], user=user)

    @staticmethod
    async def update_dataset(
        text: str,
        dataset: str,
        user: Any,
        node_set: list[str] | None = None,
    ) -> Tuple[str, bool]:
        text = (text or "").strip()
        if not text:
            return dataset, False

        digest = sha256(text.encode()).hexdigest()
        if await HashStore.contains(dataset, digest):
            if _debug_enabled():
                logger.debug("[COGNEE_DEBUG] HashStore hit dataset=%s digest=%s (skip add)", dataset, digest[:12])
            return dataset, False

        user = _to_user_with_id(user)
        await CogneeCoach._ensure_dataset_exists(dataset, user)

        info = await _safe_add(text=text, dataset_name=dataset, user=user, node_set=node_set)
        await HashStore.add(dataset, digest)

        ds_name = getattr(info, "dataset_id", None) or getattr(info, "dataset_name", None) or dataset
        return ds_name, True

    # ---------- public API ----------

    @classmethod
    async def make_request(cls, prompt: str, client_id: int) -> list[str]:
        DatasetNotFoundError, PermissionDeniedError = _exceptions()
        user = await cls._get_cognee_user()
        await cls._ensure_profile_indexed(client_id, user)
        datasets = [cls._dataset_name(client_id), cls.GLOBAL_DATASET]
        try:
            return await _c().search(prompt, datasets=datasets, user=_to_user_with_id(user))
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
        client_id: int | None,
        role: MessageRole | None = None,
        node_set: list[str] | None = None,
    ) -> None:
        """Add text to the appropriate dataset and trigger indexing if new."""
        user = await cls._get_cognee_user()
        dataset = cls._dataset_name(client_id) if client_id is not None else cls.GLOBAL_DATASET
        if role:
            text = f"{role.value}: {text}"

        try:
            dataset, created = await cls.update_dataset(text, dataset, user, node_set=node_set or [])
            if created:
                asyncio.create_task(cls._process_dataset(dataset, user))
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
        DatasetNotFoundError, _ = _exceptions()
        user = await cls._get_cognee_user()
        await cls._ensure_profile_indexed(client_id, user)
        datasets = [cls._dataset_name(client_id), cls.GLOBAL_DATASET]
        try:
            messages = await _c().search(query, datasets=datasets, top_k=5, user=_to_user_with_id(user))
        except DatasetNotFoundError:
            messages = []
        except Exception as e:
            logger.error(f"get_client_context failed: {e}")
            messages = []
        return {"messages": messages}
