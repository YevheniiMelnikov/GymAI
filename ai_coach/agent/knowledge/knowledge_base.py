import asyncio
import inspect
from dataclasses import asdict, is_dataclass
from hashlib import sha256
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, ClassVar, Iterable, Sequence, cast
from uuid import UUID

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
    _list_data_requires_user: bool | None = None
    _has_datasets_module: bool | None = None
    _warned_missing_user: bool = False

    GLOBAL_DATASET: str = settings.COGNEE_GLOBAL_DATASET
    _CLIENT_ALIAS_PREFIX: str = "kb_client_"
    _LEGACY_CLIENT_PREFIX: str = "client_"
    _PROJECTION_CHECK_QUERY: str = "__knowledge_projection_health__"
    _PROJECTION_BACKOFF_SECONDS: tuple[float, ...] = (0.5, 1.0, 2.0, 4.0)
    _FITNESS_HINTS: ClassVar[tuple[str, ...]] = (
        "сушка",
        "подсуш",
        "підсуш",
        "жир",
        "fat loss",
        "cutting",
        "дефицит",
        "дефіцит",
        "calorie",
    )
    _NEGATIVE_HINTS: ClassVar[tuple[str, ...]] = (
        "полотен",
        "рушник",
        "шкіра",
        "skin",
        "hair",
        "dryer",
        "фен",
    )
    _FITNESS_EXPANSIONS: ClassVar[tuple[str, ...]] = (
        "дефицит калорий",
        "калорійний дефіцит",
        "низький відсоток жиру",
        "reduce body fat",
        "fat loss training",
        "strength and cardio",
        "calorie deficit",
        "nutrition plan",
    )

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
    async def prune(cls) -> None:
        """Run Cognee prune routine to cleanup cached data."""
        try:
            from cognee.api.v1.prune import prune as cognee_prune  # pyrefly: ignore[import-error]
        except Exception as exc:  # pragma: no cover - import errors handled upstream
            logger.error(f"Cognee prune unavailable: {exc}")
            raise UserServiceError("Cognee prune module unavailable") from exc

        try:
            await cognee_prune.prune_data()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Cognee prune failed: {exc}")
            raise UserServiceError("Cognee prune failed") from exc

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
        """Search across client and global datasets with resiliency features."""
        normalized = query.strip()
        if not normalized:
            logger.debug(f"Knowledge search skipped client_id={client_id}: empty query")
            return []
        user = await cls._get_cognee_user()
        await cls._ensure_profile_indexed(client_id, user)
        datasets = [cls._dataset_name(client_id), cls.GLOBAL_DATASET]
        resolved_datasets: list[str] = []
        for alias in datasets:
            resolved = cls._resolve_dataset_alias(alias)
            try:
                await cls._ensure_dataset_exists(resolved, user)
            except Exception as ensure_exc:
                logger.debug(
                    f"knowledge_dataset_ensure_failed client_id={client_id} dataset={resolved} detail={ensure_exc}"
                )
            resolved_datasets.append(resolved)

        base_hash = sha256(normalized.encode()).hexdigest()[:12]
        datasets_hint = ",".join(resolved_datasets)
        logger.debug(
            f"knowledge_search_start client_id={client_id} query_hash={base_hash}"
            f" datasets={datasets_hint} top_k={k if k is not None else 'default'}"
        )

        queries = cls._expanded_queries(normalized)
        if len(queries) > 1:
            logger.debug(
                f"knowledge_search_expanded client_id={client_id} variants={len(queries)} base_query_hash={base_hash}"
            )

        fitness_query = cls._is_fitness_query(normalized)
        aggregated: list[str] = []
        seen: set[str] = set()
        for variant in queries:
            results = await cls._search_single_query(
                variant,
                resolved_datasets,
                user,
                k,
                client_id,
            )
            if not results:
                continue
            filtered = cls._filter_results(results, fitness_query)
            for item in filtered:
                cleaned = str(item or "").strip()
                if not cleaned:
                    continue
                key = cleaned.lower()
                if key in seen:
                    continue
                aggregated.append(cleaned)
                seen.add(key)
                if k is not None and len(aggregated) >= k:
                    break
            if k is not None and len(aggregated) >= k:
                break

        if k is not None:
            return aggregated[:k]
        return aggregated

    @classmethod
    async def _search_single_query(
        cls,
        query: str,
        datasets: list[str],
        user: Any | None,
        k: int | None,
        client_id: int,
    ) -> list[str]:
        query_hash = sha256(query.encode()).hexdigest()[:12]
        datasets_hint = ",".join(datasets)

        async def _search_targets(targets: list[str]) -> list[str]:
            params: dict[str, Any] = {
                "datasets": targets,
                "user": cls._to_user_or_none(user),
            }
            if k is not None:
                params["top_k"] = k
            return await cognee.search(query, **params)

        try:
            results = await _search_targets(datasets)
            logger.debug(f"knowledge_search_ok client_id={client_id} query_hash={query_hash} results={len(results)}")
            return results
        except (PermissionDeniedError, DatasetNotFoundError) as exc:
            logger.warning(f"Search issue client_id={client_id} query_hash={query_hash}: {exc}")
            return []
        except Exception as exc:
            message = str(exc)
            if cls._is_graph_missing_error(exc):
                logger.warning(
                    f"knowledge_search_graph_missing client_id={client_id} datasets={datasets_hint} detail={message}"
                )
                await cls._warm_up_datasets(datasets, user)
                try:
                    results = await _search_targets(datasets)
                    logger.debug(
                        "knowledge_search_ok client_id={} query_hash={} results={} retry=warm",
                        client_id,
                        query_hash,
                        len(results),
                    )
                    return results
                except Exception as retry_exc:
                    if not cls._is_graph_missing_error(retry_exc):
                        logger.warning(
                            f"knowledge_search_retry_non_graph_error client_id={client_id} detail={retry_exc}"
                        )
                        return []
                    logger.warning(f"knowledge_search_retry_global_only client_id={client_id} detail={retry_exc}")
                    fallback_dataset = cls._resolve_dataset_alias(cls.GLOBAL_DATASET)
                    await cls._warm_up_datasets([fallback_dataset], user)
                    try:
                        results = await _search_targets([fallback_dataset])
                        logger.debug(
                            "knowledge_search_ok client_id={} query_hash={} results={} fallback=global",
                            client_id,
                            query_hash,
                            len(results),
                        )
                        return results
                    except Exception as final_exc:
                        if cls._is_graph_missing_error(final_exc):
                            fallback_entries = await cls._fallback_dataset_entries(
                                datasets,
                                user,
                                top_k=k,
                            )
                            if fallback_entries:
                                logger.info(
                                    "knowledge_search_dataset_fallback client_id={} results={}",
                                    client_id,
                                    len(fallback_entries),
                                )
                                return fallback_entries
                            logger.warning(
                                f"knowledge_search_dataset_fallback_empty client_id={client_id} query_hash={query_hash}"
                            )
                        else:
                            logger.error(
                                "knowledge_search_retry_failed client_id={} query_hash={} detail={}",
                                client_id,
                                query_hash,
                                final_exc,
                            )
                        return []
            logger.error(f"Unexpected search error client_id={client_id}: {message}")
            return []

    @classmethod
    def _expanded_queries(cls, query: str) -> list[str]:
        variants: list[str] = []
        seen: set[str] = set()
        for candidate in (query,) + tuple(cls._fitness_query_variants(query)):
            lowered = candidate.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            variants.append(candidate)
        return variants

    @classmethod
    def _fitness_query_variants(cls, query: str) -> Iterable[str]:
        if not cls._is_fitness_query(query):
            return ()
        lowered = query.lower()
        additions: list[str] = []
        for token in cls._FITNESS_EXPANSIONS:
            token_lower = token.lower()
            if token_lower not in lowered:
                additions.append(f"{query} {token}")
        additions.extend(token for token in cls._FITNESS_EXPANSIONS if token.lower() not in lowered)
        return additions

    @classmethod
    def _filter_results(cls, results: Iterable[str], fitness_only: bool) -> list[str]:
        filtered: list[str] = []
        for item in results:
            text = str(item or "").strip()
            if not text:
                continue
            if fitness_only and cls._contains_negative_hint(text):
                continue
            filtered.append(text)
        return filtered

    @classmethod
    def _is_fitness_query(cls, query: str) -> bool:
        lowered = query.lower()
        if any(term in lowered for term in cls._NEGATIVE_HINTS):
            return False
        return any(hint in lowered for hint in cls._FITNESS_HINTS)

    @classmethod
    def _contains_negative_hint(cls, text: str) -> bool:
        lowered = text.lower()
        return any(term in lowered for term in cls._NEGATIVE_HINTS)

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
                logger.warning(f"History fetch skipped client_id={client_id}: default user unavailable")
                cls._warned_missing_user = True
            else:
                logger.debug(f"History fetch skipped client_id={client_id}: default user unavailable")
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
        except Exception:
            logger.info(f"No message history found for client_id={client_id}")
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
        normalized = name.strip()
        if not normalized:
            return name
        if normalized.startswith(cls._CLIENT_ALIAS_PREFIX):
            suffix = normalized[len(cls._CLIENT_ALIAS_PREFIX) :]
            try:
                client_id = int(suffix)
            except ValueError:
                return normalized
            return cls._dataset_name(client_id)
        if normalized.startswith(cls._LEGACY_CLIENT_PREFIX):
            suffix = normalized[len(cls._LEGACY_CLIENT_PREFIX) :]
            try:
                client_id = int(suffix)
            except ValueError:
                return normalized
            return cls._dataset_name(client_id)
        return normalized

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
        """Generate canonical dataset alias for a client profile."""
        return f"{cls._CLIENT_ALIAS_PREFIX}{client_id}"

    @classmethod
    def _describe_list_data(cls, list_data: Callable[..., Awaitable[Iterable[Any]]]) -> tuple[bool | None, bool | None]:
        try:
            signature = inspect.signature(list_data)
        except (TypeError, ValueError):
            return None, None
        parameter = signature.parameters.get("user")
        if parameter is None:
            return False, False
        supports_keyword = parameter.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
        requires_user = parameter.default is inspect._empty
        return supports_keyword, requires_user

    @classmethod
    async def _fetch_dataset_rows(
        cls,
        list_data: Callable[..., Awaitable[Iterable[Any]]],
        dataset: str,
        user_ns: Any | None,
    ) -> list[Any]:
        """Fetch dataset rows, gracefully handling legacy signatures."""
        if user_ns is not None:
            if cls._list_data_supports_user is None or cls._list_data_requires_user is None:
                supports, requires = cls._describe_list_data(list_data)
                if supports is not None:
                    cls._list_data_supports_user = supports
                if requires is not None:
                    cls._list_data_requires_user = requires

        if user_ns is not None and cls._list_data_supports_user is not False:
            try:
                rows = await list_data(dataset, user=user_ns)
            except TypeError:
                logger.debug("cognee.datasets.list_data rejected keyword 'user', retrying without keyword")
                cls._list_data_supports_user = False
                if cls._list_data_requires_user:
                    logger.debug("cognee.datasets.list_data requires user context, retrying positional call")
                    rows = await list_data(dataset, user_ns)
                    cls._list_data_supports_user = True
                    return list(rows)
            else:
                cls._list_data_supports_user = True
                return list(rows)

        if user_ns is not None and cls._list_data_requires_user:
            logger.debug("cognee.datasets.list_data requires user context, retrying positional call")
            rows = await list_data(dataset, user_ns)
            cls._list_data_supports_user = True
            return list(rows)

        try:
            rows = await list_data(dataset)
        except TypeError as exc:
            if user_ns is not None:
                logger.debug(
                    f"cognee.datasets.list_data raised {exc.__class__.__name__}: retrying with positional user"
                )
                rows = await list_data(dataset, user_ns)
                cls._list_data_supports_user = True
                cls._list_data_requires_user = True
                return list(rows)
            raise
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
            await cls._project_dataset(ds, user)

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

    @classmethod
    def _is_graph_missing_error(cls, exc: Exception) -> bool:
        message = str(exc)
        if "Empty graph" in message or "empty graph" in message:
            return True
        if "EntityNotFound" in exc.__class__.__name__:
            return True
        status = getattr(exc, "status_code", None)
        return status == 404

    @classmethod
    async def _warm_up_datasets(cls, datasets: list[str], user: Any | None) -> None:
        """Ensure datasets are cognified before retrying a search."""
        for dataset in datasets:
            try:
                await cls._process_dataset(dataset, user)
            except Exception as exc:  # noqa: BLE001 - logging context is sufficient here
                logger.warning(f"knowledge_dataset_warmup_failed dataset={dataset} detail={exc}")

    @classmethod
    async def _project_dataset(
        cls,
        dataset: str,
        user: Any | None,
        *,
        allow_rebuild: bool = True,
    ) -> None:
        """Run cognify and wait for the dataset projection to become available."""
        user_ns = cls._to_user_or_none(user)
        try:
            await cognee.cognify(datasets=[dataset], user=user_ns)  # pyrefly: ignore[bad-argument-type]
        except FileNotFoundError as exc:
            logger.warning(f"knowledge_dataset_storage_missing dataset={dataset} detail={exc}")
            cls._log_storage_state(dataset)
            await HashStore.clear(dataset)
            if allow_rebuild and await cls.rebuild_dataset(dataset, user):
                logger.info(f"knowledge_dataset_rebuilt dataset={dataset}")
                await cls._project_dataset(dataset, user, allow_rebuild=False)
                return
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"knowledge_dataset_cognify_failed dataset={dataset} detail={exc}")
            raise

        await cls._wait_for_projection(dataset, user_ns)

    @classmethod
    async def rebuild_dataset(cls, dataset: str, user: Any | None) -> bool:
        """Rebuild dataset content by re-adding raw entries and clearing hash store."""
        try:
            await cls._ensure_dataset_exists(dataset, user)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"knowledge_dataset_rebuild_ensure_failed dataset={dataset} detail={exc}")
        try:
            entries = await cls._list_dataset_entries(dataset, user)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"knowledge_dataset_rebuild_list_failed dataset={dataset} detail={exc}")
            return False
        if not entries:
            logger.warning(f"knowledge_dataset_rebuild_skipped dataset={dataset}: no_entries")
            return False
        await HashStore.clear(dataset)
        user_ns = cls._to_user_or_none(user)
        reinserted = 0
        for text in entries:
            normalized = str(text or "").strip()
            if not normalized:
                continue
            try:
                await _safe_add(
                    normalized,
                    dataset_name=dataset,
                    user=user_ns,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"knowledge_dataset_rebuild_add_failed dataset={dataset} detail={exc}")
                continue
            digest = sha256(normalized.encode()).hexdigest()
            await HashStore.add(dataset, digest)
            reinserted += 1
        if reinserted == 0:
            logger.warning(f"knowledge_dataset_rebuild_skipped dataset={dataset}: no_valid_entries")
            return False
        logger.info(f"knowledge_dataset_rebuild_ready dataset={dataset} documents={reinserted}")
        return True

    @classmethod
    async def _wait_for_projection(cls, dataset: str, user_ns: Any | None) -> None:
        if not cls._PROJECTION_BACKOFF_SECONDS:
            return
        for delay in cls._PROJECTION_BACKOFF_SECONDS:
            if await cls._is_projection_ready(dataset, user_ns):
                logger.debug(f"knowledge_dataset_projected dataset={dataset}")
                return
            await asyncio.sleep(delay)
        if await cls._is_projection_ready(dataset, user_ns):
            logger.debug(f"knowledge_dataset_projected dataset={dataset} after_timeout=True")
            return
        logger.warning(f"knowledge_dataset_projection_timeout dataset={dataset}")

    @classmethod
    def _log_storage_state(cls, dataset: str) -> None:
        storage_info = CogneeConfig.describe_storage()
        logger.warning(
            f"knowledge_dataset_storage_state dataset={dataset} storage_root={storage_info.get('root')} "
            f"root_exists={storage_info.get('root_exists')} root_writable={storage_info.get('root_writable')} "
            f"entries={storage_info.get('entries_count')} sample={storage_info.get('entries_sample')} "
            f"package_path={storage_info.get('package_path')} package_exists={storage_info.get('package_exists')} "
            f"package_is_symlink={storage_info.get('package_is_symlink')} "
            f"package_target={storage_info.get('package_target')}"
        )

    @classmethod
    async def _is_projection_ready(cls, dataset: str, user_ns: Any | None) -> bool:
        """Return True if the dataset projection looks ready for querying."""
        try:
            await cognee.search(
                cls._PROJECTION_CHECK_QUERY,
                datasets=[dataset],
                user=user_ns,
                top_k=1,
            )
        except Exception as exc:  # noqa: BLE001
            if cls._is_graph_missing_error(exc):
                return False
            logger.debug(f"knowledge_projection_probe_error dataset={dataset} detail={exc}")
            return True
        return True

    @classmethod
    async def _fallback_dataset_entries(
        cls,
        datasets: Sequence[str],
        user: Any | None,
        *,
        top_k: int | None,
    ) -> list[str]:
        """Return raw dataset entries when graph search is unavailable."""
        collected: list[str] = []
        limit = top_k or 6
        for dataset in datasets:
            entries = await cls._list_dataset_entries(dataset, user)
            for item in entries:
                normalized = item.strip()
                if not normalized:
                    continue
                collected.append(normalized)
                if len(collected) >= limit:
                    return collected
        return collected

    @classmethod
    async def fallback_entries(cls, client_id: int, limit: int = 6) -> list[str]:
        """Expose raw dataset entries for resiliency fallbacks."""
        user = await cls._get_cognee_user()
        aliases = [cls._dataset_name(client_id), cls.GLOBAL_DATASET]
        datasets = [cls._resolve_dataset_alias(alias) for alias in aliases]
        return await cls._fallback_dataset_entries(datasets, user, top_k=limit)

    @classmethod
    async def _list_dataset_entries(cls, dataset: str, user: Any | None) -> list[str]:
        datasets_module = getattr(cognee, "datasets", None)
        if datasets_module is None:
            logger.debug(f"knowledge_dataset_list_skipped dataset={dataset}: datasets module missing")
            return []
        list_data = getattr(datasets_module, "list_data", None)
        if not callable(list_data):
            logger.debug(f"knowledge_dataset_list_skipped dataset={dataset}: list_data missing")
            return []
        try:
            await cls._ensure_dataset_exists(dataset, user)
        except Exception as exc:  # pragma: no cover - best effort to keep flow running
            logger.debug(f"knowledge_dataset_list_ensure_failed dataset={dataset} detail={exc}")
        user_ns = cls._to_user_or_none(user)
        identifier = await cls._resolve_dataset_identifier(dataset, user)
        try:
            rows = await cls._fetch_dataset_rows(
                cast(Callable[..., Awaitable[Iterable[Any]]], list_data),
                identifier,
                user_ns,
            )
        except Exception as exc:  # noqa: BLE001 - dataset listing is best effort
            logger.debug(f"knowledge_dataset_list_failed dataset={dataset} detail={exc}")
            return []
        texts: list[str] = []
        for row in rows:
            text = getattr(row, "text", None)
            if text:
                texts.append(str(text))
        return texts

    @classmethod
    async def debug_snapshot(cls, client_id: int | None = None) -> dict[str, Any]:
        """Return diagnostic information about configured datasets."""
        user = await cls._get_cognee_user()
        aliases: list[str] = []
        if client_id is not None:
            aliases.append(cls._dataset_name(client_id))
        aliases.append(cls.GLOBAL_DATASET)
        seen: set[str] = set()
        datasets_info: list[dict[str, Any]] = []
        for alias in aliases:
            if alias in seen:
                continue
            seen.add(alias)
            info = await cls._build_dataset_snapshot(alias, user)
            datasets_info.append(info)
        return {"datasets": datasets_info}

    @classmethod
    async def _build_dataset_snapshot(cls, alias: str, user: Any | None) -> dict[str, Any]:
        resolved = cls._resolve_dataset_alias(alias)
        user_ns = cls._to_user_or_none(user)
        info: dict[str, Any] = {
            "alias": alias,
            "resolved": resolved,
            "id": resolved,
            "documents": None,
            "projected": None,
            "last_error": None,
        }
        metadata = await cls._get_dataset_metadata(resolved, user)
        if metadata is not None:
            identifier = getattr(metadata, "id", None) or getattr(metadata, "dataset_id", None)
            if identifier:
                info["id"] = str(identifier)
            updated_at = getattr(metadata, "updated_at", None) or getattr(metadata, "updatedAt", None)
            if updated_at is not None:
                info["updated_at"] = str(updated_at)
        try:
            entries = await cls._list_dataset_entries(resolved, user)
        except Exception as exc:  # noqa: BLE001
            info["last_error"] = str(exc)
            entries = []
        if entries:
            info["documents"] = len(entries)
        else:
            info["documents"] = 0
        try:
            info["projected"] = await cls._is_projection_ready(resolved, user_ns)
        except Exception as exc:  # noqa: BLE001
            info["last_error"] = str(exc)
        return info

    @classmethod
    async def _resolve_dataset_identifier(cls, dataset: str, user: Any | None) -> str:
        metadata = await cls._get_dataset_metadata(dataset, user)
        if metadata is not None:
            for attr in ("id", "dataset_id"):
                identifier = getattr(metadata, attr, None)
                if identifier:
                    return str(identifier)
        return dataset

    @classmethod
    async def _get_dataset_metadata(cls, dataset: str, user: Any | None) -> Any | None:
        try:  # pragma: no cover - optional dependency
            from cognee.modules.data.methods import get_authorized_dataset_by_name  # type: ignore
        except Exception:
            return None
        try:
            return await get_authorized_dataset_by_name(
                dataset, cls._to_user_or_none(user), "read"
            )  # pyrefly: ignore[bad-argument-type]
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"knowledge_dataset_metadata_failed dataset={dataset} detail={exc}")
            return None
