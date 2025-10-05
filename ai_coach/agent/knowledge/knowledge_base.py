import asyncio
import os
from dataclasses import asdict, is_dataclass
from hashlib import sha256
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Iterable, cast
from uuid import NAMESPACE_DNS, UUID, uuid5

from loguru import logger

from ai_coach.agent.knowledge.base_knowledge_loader import KnowledgeLoader
from ai_coach.agent.knowledge.cognee_config import CogneeConfig
from ai_coach.agent.knowledge.utils.hash_store import HashStore
from ai_coach.agent.knowledge.utils.lock_cache import LockCache
from ai_coach.schemas import CogneeUser
from ai_coach.types import MessageRole
from config.app_settings import settings
from core.exceptions import UserServiceError
from core.services import APIService
from core.schemas import Client

import cognee  # type: ignore

try:
    from cognee.modules.users.methods.get_default_user import get_default_user  # type: ignore
except Exception:

    async def get_default_user() -> Any | None:  # type: ignore
        return None


try:  # pragma: no cover - optional dependency
    from cognee.modules.data.exceptions import DatasetNotFoundError  # type: ignore
    from cognee.modules.users.exceptions.exceptions import PermissionDeniedError  # type: ignore
except Exception:  # pragma: no cover - stubs for tests

    class DatasetNotFoundError(Exception):
        pass

    class PermissionDeniedError(Exception):
        pass


async def _safe_add(*args, **kwargs):
    return await cognee.add(*args, **kwargs)


class KnowledgeBase:
    """Cognee-backed knowledge storage for the coach agent."""

    _loader: KnowledgeLoader | None = None
    _cognify_locks: LockCache = LockCache()
    _user: Any | None = None
    _list_data_supports_user: bool | None = None
    _has_datasets_module: bool | None = None
    _warned_missing_user: bool = False

    GLOBAL_DATASET: str = os.environ.get("COGNEE_GLOBAL_DATASET", "external_docs")
    _CLIENT_DATASET_NAMESPACE: UUID | None = None
    _CLIENT_ALIAS_PREFIX: str = "client_"

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
    async def refresh(cls) -> None:
        """Re-cognify global dataset and refresh loader if available."""
        user = await cls._get_cognee_user()
        ds = cls._resolve_dataset_alias(cls.GLOBAL_DATASET)
        await cls._ensure_dataset_exists(ds, user)
        if cls._loader:
            await cls._loader.refresh()
        try:
            await cognee.cognify(datasets=[ds], user=cls._to_user_or_none(user))  # pyrefly: ignore[bad-argument-type]
        except (PermissionDeniedError, DatasetNotFoundError) as e:
            logger.error(f"Knowledge base update skipped: {e}")

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
            info = await _safe_add(
                text,
                dataset_name=ds_name,
                user=cls._to_user_or_none(user),  # pyrefly: ignore[bad-argument-type]
                node_set=node_set,
            )
        except (DatasetNotFoundError, PermissionDeniedError):
            raise
        await HashStore.add(ds_name, digest)
        resolved = ds_name
        if info is not None:
            for candidate in (getattr(info, "dataset_id", None), getattr(info, "dataset_name", None)):
                if isinstance(candidate, str) and candidate:
                    try:
                        resolved = str(UUID(candidate))
                        break
                    except ValueError:
                        continue
        return resolved, True

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
                "user": cls._to_user_or_none(user),
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
            logger.debug(f"Updating dataset {ds}")
            ds, created = await cls.update_dataset(text, ds, user, node_set=node_set or [])
            if created:
                task = asyncio.create_task(cls._process_dataset(ds, user))
                task.add_done_callback(cls._log_task_exception)
        except PermissionDeniedError:
            raise
        except Exception as exc:
            logger.warning(f"Add text skipped: {exc}", exc_info=True)

    @classmethod
    async def save_client_message(cls, text: str, client_id: int) -> None:
        await cls.add_text(text, client_id=client_id, role=MessageRole.CLIENT)

    @classmethod
    async def save_ai_message(cls, text: str, client_id: int) -> None:
        await cls.add_text(text, client_id=client_id, role=MessageRole.AI_COACH)

    @classmethod
    async def get_message_history(cls, client_id: int, limit: int | None = None) -> list[str]:
        """Return recent chat messages for a client."""
        dataset: str = cls._resolve_dataset_alias(cls._dataset_name(client_id))
        user: Any | None = await cls._get_cognee_user()
        if user is None:
            if not cls._warned_missing_user:
                logger.warning("History fetch skipped client_id=%s: default user unavailable", client_id)
                cls._warned_missing_user = True
            else:
                logger.debug("History fetch skipped client_id=%s: default user unavailable", client_id)
            return []
        try:
            await cls._ensure_dataset_exists(dataset, user)
        except Exception as exc:  # pragma: no cover - non-critical indexing failure
            logger.debug(f"Dataset ensure skipped client_id={client_id}: {exc}")
        datasets_module = getattr(cognee, "datasets", None)
        if datasets_module is None:
            if cls._has_datasets_module is not False:
                logger.warning(f"History fetch skipped client_id={client_id}: datasets module unavailable")
            cls._has_datasets_module = False
            return []

        list_data = getattr(datasets_module, "list_data", None)
        if not callable(list_data):
            if cls._has_datasets_module is not False:
                logger.warning(
                    f"History fetch skipped client_id={client_id}: list_data callable missing",
                )
            cls._has_datasets_module = False
            return []

        cls._has_datasets_module = True
        list_data_callable = cast(Callable[..., Awaitable[Iterable[Any]]], list_data)
        user_ns: Any | None = cls._to_user_or_none(user)
        try:
            data = await cls._fetch_dataset_rows(list_data_callable, dataset, user_ns)
        except Exception as e:
            logger.warning(f"History fetch failed client_id={client_id}: {e}")
            return []
        messages: list[str] = []
        for item in data:
            text = getattr(item, "text", None)
            if text:
                messages.append(str(text))
        limit = limit or settings.CHAT_HISTORY_LIMIT
        return messages[-limit:]

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
        """Map dataset alias to the canonical dataset identifier."""
        if name.startswith(cls._CLIENT_ALIAS_PREFIX):
            suffix = name[len(cls._CLIENT_ALIAS_PREFIX) :]
            try:
                client_id = int(suffix)
            except ValueError:
                return name
            return cls._dataset_name(client_id)
        return name

    @classmethod
    async def _ensure_dataset_exists(cls, name: str, user: Any | None) -> None:
        """Create dataset if it does not exist for the given user."""
        user_ns = cls._to_user_or_none(user)
        if user_ns is None:
            logger.debug(f"Dataset ensure skipped dataset={name}: user context unavailable")
            return
        try:
            from cognee.modules.data.methods import (  # type: ignore
                get_authorized_dataset_by_name,
                create_authorized_dataset,
            )
        except Exception:
            return
        exists = await get_authorized_dataset_by_name(name, user_ns, "write")  # pyrefly: ignore[bad-argument-type]
        if exists is None:
            await create_authorized_dataset(name, user_ns)  # pyrefly: ignore[bad-argument-type]

    @classmethod
    def _dataset_name(cls, client_id: int) -> str:
        """Generate deterministic dataset identifier for a client profile."""
        namespace = cls._client_namespace()
        return str(uuid5(namespace, f"client-profile:{client_id}"))

    @classmethod
    def _client_namespace(cls) -> UUID:
        if cls._CLIENT_DATASET_NAMESPACE is None:
            raw = getattr(settings, "COGNEE_CLIENT_DATASET_NAMESPACE", None)
            if not raw:
                seed = getattr(settings, "SECRET_KEY", "") or getattr(settings, "SITE_NAME", "") or "gymbot"
                base_namespace = uuid5(NAMESPACE_DNS, "gymbot.cognee")
                raw = str(uuid5(base_namespace, seed))
            try:
                cls._CLIENT_DATASET_NAMESPACE = UUID(str(raw))
            except ValueError as exc:  # pragma: no cover - configuration error
                raise RuntimeError("Invalid COGNEE_CLIENT_DATASET_NAMESPACE value") from exc
        return cls._CLIENT_DATASET_NAMESPACE

    @classmethod
    async def _fetch_dataset_rows(
        cls,
        list_data: Callable[..., Awaitable[Iterable[Any]]],
        dataset: str,
        user_ns: Any | None,
    ) -> list[Any]:
        """Fetch dataset rows, gracefully handling legacy signatures."""
        if user_ns is not None and cls._list_data_supports_user is not False:
            try:
                rows = await list_data(dataset, user=user_ns)
            except TypeError:
                logger.debug("cognee.datasets.list_data does not accept 'user', retrying without it")
                cls._list_data_supports_user = False
            else:
                cls._list_data_supports_user = True
                return list(rows)
        rows = await list_data(dataset)
        return list(rows)

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
            client = await APIService.profile.get_client(client_id)
        except UserServiceError as e:
            logger.warning(f"Failed to fetch client id={client_id}: {e}")
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
            await cognee.cognify(datasets=[ds], user=cls._to_user_or_none(user))  # pyrefly: ignore[bad-argument-type]

    @staticmethod
    def _log_task_exception(task: asyncio.Task[Any]) -> None:
        """Log exception from a background task."""
        if exc := task.exception():
            logger.warning(f"Dataset processing failed: {exc}", exc_info=True)

    @classmethod
    def _to_user_or_none(cls, user: Any) -> Any | None:
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
