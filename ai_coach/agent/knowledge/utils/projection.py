from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any, ClassVar, Optional, TYPE_CHECKING

from loguru import logger

from ai_coach.agent.knowledge.schemas import ProjectionStatus
from ai_coach.agent.knowledge.utils.datasets import DatasetService
from ai_coach.agent.knowledge.utils.storage import StorageService
from config.app_settings import settings
from core.utils.redis_lock import redis_try_lock

if TYPE_CHECKING:
    from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase

Waiter = Callable[..., Awaitable[ProjectionStatus]]


class ProjectionService:
    """Coordinate dataset projection lifecycle and retry logic."""

    _MAX_REBUILD_ATTEMPTS: ClassVar[int] = 3
    _COGNIFY_SEMAPHORE: ClassVar[asyncio.Semaphore | None] = None
    _LAST_PROJECTION_START: ClassVar[dict[str, float]] = {}
    _STALL_STATE: ClassVar[dict[str, dict[str, float | int | None]]] = {}
    _SCHEDULED_TASKS: ClassVar[dict[str, asyncio.Task[None]]] = {}
    _SCHEDULED_REQUESTS: ClassVar[dict[str, dict[str, Any]]] = {}

    def __init__(
        self,
        dataset_service: DatasetService,
        storage_service: StorageService,
    ):
        self.dataset_service = dataset_service
        self.storage_service = storage_service
        self._wait_callback: Optional[Waiter] = None
        self._knowledge_base: Optional["KnowledgeBase"] = None

    def set_waiter(self, waiter: Waiter) -> None:
        self._wait_callback = waiter

    def attach_knowledge_base(self, knowledge_base: "KnowledgeBase") -> None:
        self._knowledge_base = knowledge_base

    async def shutdown(self) -> None:
        tasks = list(self._SCHEDULED_TASKS.values())
        self._SCHEDULED_TASKS.clear()
        self._SCHEDULED_REQUESTS.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def _batch_window_s() -> float:
        return max(float(settings.COGNEE_PROJECTION_BATCH_WINDOW_S), 0.0)

    @classmethod
    def is_batching_enabled(cls) -> bool:
        return cls._batch_window_s() > 0

    def record_wait_attempts(self, dataset: str, attempts: int, status: ProjectionStatus) -> None:
        alias = self.dataset_service.alias_for_dataset(dataset)
        logger.debug(f"projection.wait dataset={alias} attempts={attempts} status={status.name.lower()}")

    @classmethod
    def _should_debounce(cls, alias: str) -> bool:
        min_interval = float(settings.COGNEE_PROJECTION_DEBOUNCE_S)
        if min_interval <= 0:
            return False
        now = monotonic()
        last = cls._LAST_PROJECTION_START.get(alias)
        if last is None:
            cls._LAST_PROJECTION_START[alias] = now
            return False
        elapsed = now - last
        if elapsed < min_interval:
            return True
        cls._LAST_PROJECTION_START[alias] = now
        return False

    async def _should_debounce_redis(self, alias: str) -> bool:
        min_interval = float(settings.COGNEE_PROJECTION_DEBOUNCE_S)
        if min_interval <= 0:
            return False
        ttl_ms = int(min_interval * 1000)
        try:
            async with redis_try_lock(f"locks:cognee_projection:{alias}", ttl_ms=ttl_ms, wait=False) as got_lock:
                return not got_lock
        except Exception as exc:  # noqa: BLE001 - best-effort debounce
            logger.debug("projection:debounce_redis_failed dataset={} detail={}", alias, exc)
            return False

    @classmethod
    def _get_cognify_semaphore(cls) -> asyncio.Semaphore:
        if cls._COGNIFY_SEMAPHORE is None:
            limit = max(int(settings.COGNEE_PROJECTION_MAX_CONCURRENCY), 1)
            cls._COGNIFY_SEMAPHORE = asyncio.Semaphore(limit)
        return cls._COGNIFY_SEMAPHORE

    @classmethod
    def _stall_state(cls, alias: str) -> dict[str, float | int | None]:
        state = cls._STALL_STATE.get(alias)
        if state is None:
            state = {
                "text_rows": None,
                "chunk_rows": None,
                "graph_nodes": None,
                "graph_edges": None,
                "no_progress": 0,
                "blocked_until": 0.0,
            }
            cls._STALL_STATE[alias] = state
        return state

    @classmethod
    def _is_blocked(cls, alias: str) -> bool:
        state = cls._stall_state(alias)
        blocked_until = float(state.get("blocked_until") or 0.0)
        return blocked_until > monotonic()

    @classmethod
    def _record_progress(cls, alias: str, counts: dict[str, int]) -> bool:
        state = cls._stall_state(alias)
        prev_text_raw = state.get("text_rows")
        prev_chunk_raw = state.get("chunk_rows")
        prev_nodes_raw = state.get("graph_nodes")
        prev_edges_raw = state.get("graph_edges")

        prev_text = int(prev_text_raw or 0)
        prev_chunk = int(prev_chunk_raw or 0)
        prev_nodes = int(prev_nodes_raw or 0)
        prev_edges = int(prev_edges_raw or 0)

        text_rows = int(counts.get("text_rows") or 0)
        chunk_rows = int(counts.get("chunk_rows") or 0)
        graph_nodes = int(counts.get("graph_nodes") or 0)
        graph_edges = int(counts.get("graph_edges") or 0)

        progressed = (
            prev_text_raw is None
            or prev_chunk_raw is None
            or prev_nodes_raw is None
            or prev_edges_raw is None
            or text_rows != prev_text
            or chunk_rows != prev_chunk
            or graph_nodes != prev_nodes
            or graph_edges != prev_edges
        )
        if progressed:
            state["no_progress"] = 0
        else:
            state["no_progress"] = int(state.get("no_progress") or 0) + 1

        state["text_rows"] = text_rows
        state["chunk_rows"] = chunk_rows
        state["graph_nodes"] = graph_nodes
        state["graph_edges"] = graph_edges

        stall_limit = max(int(settings.COGNEE_PROJECTION_STALL_LIMIT), 0)
        if stall_limit <= 0:
            return False
        if int(state["no_progress"]) >= stall_limit:
            cooldown_s = max(float(settings.COGNEE_PROJECTION_STALL_COOLDOWN_S), 0.0)
            state["blocked_until"] = monotonic() + cooldown_s
            return True
        return False

    @staticmethod
    def _is_retryable_cognify_error(exc: Exception) -> bool:
        message = str(exc)
        if "DeadlockDetected" in message or "TransientError" in message:
            return True
        if "ConnectTimeout" in message or "ResponseHandlingException" in message:
            return True
        try:
            import httpcore
            import httpx
            from qdrant_client.http.exceptions import ResponseHandlingException
            from qdrant_client.http.exceptions import UnexpectedResponse
        except Exception:
            httpcore = None  # type: ignore[assignment]
            httpx = None  # type: ignore[assignment]
            ResponseHandlingException = None  # type: ignore[assignment]
            UnexpectedResponse = None  # type: ignore[assignment]
        if httpcore is not None and isinstance(exc, httpcore.ConnectTimeout):
            return True
        if httpx is not None and isinstance(exc, httpx.ConnectTimeout):
            return True
        if ResponseHandlingException is not None and isinstance(exc, ResponseHandlingException):
            return True
        if UnexpectedResponse is not None and isinstance(exc, UnexpectedResponse):
            status = getattr(exc, "status_code", None)
            if status in {408, 429, 500, 502, 503, 504}:
                return True
        return False

    def _maybe_mark_degraded(self, exc: Exception) -> None:
        kb = self._knowledge_base
        if kb is None:
            return
        message = str(exc)
        lowered = message.lower()
        reason = None
        if "qdrant" in lowered or "uploading data points" in lowered:
            reason = "qdrant_error"
        elif "deadlockdetected" in lowered or "neo4j" in lowered:
            reason = "neo4j_deadlock"
        elif "request timeout" in lowered or "unexpected response: 408" in lowered:
            reason = "request_timeout"
        if reason is None:
            return
        cooldown_s = max(float(settings.COGNEE_PROJECTION_DEGRADED_COOLDOWN_S), 0.0)
        kb.mark_degraded(reason=reason, cooldown_s=cooldown_s)

    @staticmethod
    def _retry_delay_s(attempt: int) -> float:
        base = float(settings.COGNEE_PROJECTION_RETRY_INITIAL_DELAY)
        factor = float(settings.COGNEE_PROJECTION_RETRY_BACKOFF_FACTOR)
        delay = base * (factor ** max(attempt - 1, 0))
        return min(delay, float(settings.COGNEE_PROJECTION_RETRY_MAX_DELAY))

    async def _schedule_projection(self, dataset: str, user: Any | None, *, allow_rebuild: bool) -> None:
        alias = self.dataset_service.alias_for_dataset(dataset)
        delay_s = self._batch_window_s()
        if delay_s <= 0:
            return
        request = {
            "dataset": dataset,
            "user": user,
            "allow_rebuild": allow_rebuild,
        }
        self._SCHEDULED_REQUESTS[alias] = request
        existing = self._SCHEDULED_TASKS.get(alias)
        if existing and not existing.done():
            existing.cancel()

        async def _run() -> None:
            try:
                await asyncio.sleep(delay_s)
                payload = self._SCHEDULED_REQUESTS.get(alias, request)
                await self._project_now(
                    payload["dataset"],
                    payload.get("user"),
                    allow_rebuild=bool(payload.get("allow_rebuild")),
                )
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"projection.scheduled_failed dataset={alias} detail={exc}")
            finally:
                self._SCHEDULED_TASKS.pop(alias, None)

        self._SCHEDULED_TASKS[alias] = asyncio.create_task(_run())
        logger.info(f"projection.scheduled dataset={alias} delay_s={delay_s:.0f}")

    async def _project_now(self, dataset: str, user: Any | None, *, allow_rebuild: bool = True) -> None:
        await self._project_dataset(
            dataset,
            user,
            allow_rebuild=allow_rebuild,
            immediate=True,
        )

    @classmethod
    def clear_stall(cls, alias: str) -> None:
        state = cls._stall_state(alias)
        state["text_rows"] = None
        state["chunk_rows"] = None
        state["graph_nodes"] = None
        state["graph_edges"] = None
        state["no_progress"] = 0
        state["blocked_until"] = 0.0

    async def ensure_dataset_projected(
        self, dataset: str, user: Any | None, *, timeout_s: float | None = None
    ) -> ProjectionStatus:
        alias = self.dataset_service.alias_for_dataset(dataset)
        user_ctx = self.dataset_service.to_user_ctx(user)

        if user_ctx is None:
            logger.warning(f"knowledge_projection_skipped dataset={alias} reason=user_context_unavailable")
            return ProjectionStatus.USER_CONTEXT_UNAVAILABLE

        wait_timeout = timeout_s if timeout_s is not None else 20.0
        for attempt in range(self._MAX_REBUILD_ATTEMPTS):
            try:
                await self.dataset_service.ensure_dataset_exists(alias, user_ctx)
            except Exception as exc:
                logger.warning(f"knowledge_projection_dataset_missing dataset={alias} detail={exc}")
                return ProjectionStatus.FATAL_ERROR

            ready, reason = await self.probe(alias, user)
            if ready:
                self.dataset_service.add_projected_dataset(alias)
                return ProjectionStatus.READY
            if reason == "no_rows_in_dataset":
                self.dataset_service.add_projected_dataset(alias)
                return ProjectionStatus.READY_EMPTY

            logger.debug(
                f"knowledge_projection_ensure dataset={alias} attempt={attempt + 1} ready={ready} reason={reason}"
            )

            wait_status = await self.wait(dataset, user=user, timeout=wait_timeout)
            if wait_status in (ProjectionStatus.READY, ProjectionStatus.READY_EMPTY):
                self.dataset_service.add_projected_dataset(alias)
                return wait_status

            if not settings.COGNEE_ENABLE_AGGRESSIVE_REBUILD:
                break

            try:
                entries = await self.dataset_service.list_dataset_entries(alias, user_ctx)
            except Exception as exc:
                logger.warning(f"projection:ensure_list_failed dataset={alias} detail={exc}")
                entries = []

            if entries:
                missing, healed = await self.storage_service.heal_dataset_storage(
                    alias, user_ctx, entries=entries, reason="ensure_projection"
                )
                if healed > 0:
                    retry_timeout = min(max(wait_timeout, 0.0), 5.0)
                    retry_status = await self.wait(dataset, user=user, timeout=retry_timeout)
                    if retry_status == ProjectionStatus.READY:
                        self.dataset_service.add_projected_dataset(alias)
                        return ProjectionStatus.READY

        logger.warning(f"projection:ensure_failed dataset={alias} attempts={self._MAX_REBUILD_ATTEMPTS}")
        return ProjectionStatus.TIMEOUT

    async def wait(self, dataset: str, user: Any | None, *, timeout: float) -> ProjectionStatus:
        alias = self.dataset_service.alias_for_dataset(dataset)
        if self._wait_callback is None:
            self.dataset_service.log_once(
                logging.DEBUG,
                "projection:waiter_missing",
                dataset=alias,
                timeout_s=timeout,
                min_interval=60.0,
            )
            return ProjectionStatus.TIMEOUT
        return await self._wait_callback(dataset, user, timeout=timeout)

    async def wait_for_projection(self, dataset: str, user: Any | None, *, timeout: float) -> ProjectionStatus:
        return await self.wait(dataset, user=user, timeout=timeout)

    async def probe(self, dataset: str, user: Any | None) -> tuple[bool, str]:
        alias = self.dataset_service.alias_for_dataset(dataset)
        user_ctx = self.dataset_service.to_user_ctx(user)
        if user_ctx is None:
            self.dataset_service.log_once(
                logging.WARNING,
                "projection:probe_skipped",
                dataset=alias,
                reason="user_context_unavailable",
                min_interval=30.0,
            )
            return False, "fatal_error"

        try:
            await self.dataset_service.ensure_dataset_exists(alias, user_ctx)
        except Exception as exc:
            self.dataset_service.log_once(
                logging.WARNING,
                "projection:probe_failed",
                dataset=alias,
                reason="fatal_error",
                detail=str(exc),
                min_interval=30.0,
            )
            return False, "fatal_error"

        try:
            dataset_id = await self.dataset_service.get_dataset_id(alias, user_ctx)
        except Exception as exc:
            self.dataset_service.log_once(
                logging.WARNING,
                "projection:probe_failed",
                dataset=alias,
                reason="fatal_error",
                detail=str(exc),
                min_interval=30.0,
            )
            return False, "fatal_error"

        if not dataset_id:
            self.dataset_service.log_once(
                logging.DEBUG,
                "projection:not_found",
                dataset=alias,
                min_interval=30.0,
            )
            return False, "not_found"

        try:
            rows = await self.dataset_service.list_dataset_entries(alias, user_ctx)
        except Exception as exc:
            self.dataset_service.log_once(
                logging.WARNING,
                "projection:probe_failed",
                dataset=alias,
                reason="fatal_error",
                detail=str(exc),
                min_interval=30.0,
            )
            return False, "fatal_error"

        logger.debug(f"projection.rows dataset={alias} rows={len(rows)}")

        if not rows:
            logger.debug(f"projection.no_rows dataset={alias} reason=dataset_entries_empty")
            self.dataset_service.log_once(
                logging.DEBUG,
                "projection:skip_no_rows",
                dataset=alias,
                min_interval=10.0,
            )
            logger.debug(f"projection:skip_no_rows dataset={alias} rows=0")
            return False, "no_rows_in_dataset"

        valid_rows = sum(1 for row in rows if str(getattr(row, "text", "") or "").strip())
        if valid_rows == 0:
            self.dataset_service.log_once(
                logging.DEBUG,
                "projection:pending",
                dataset=alias,
                rows=len(rows),
                min_interval=10.0,
            )
            return False, "pending"

        self.dataset_service.log_once(
            logging.DEBUG,
            "projection:ready",
            dataset=alias,
            rows=valid_rows,
            min_interval=5.0,
        )
        return True, "ready"

    async def is_projection_ready(self, dataset: str, user: Any | None) -> tuple[ProjectionStatus, str]:
        ok, reason = await self.probe(dataset, user)
        return (ProjectionStatus.READY if ok else ProjectionStatus.UNKNOWN, reason or "")

    async def project_dataset(self, dataset: str, user: Any | None, *, allow_rebuild: bool = True) -> None:
        await self._project_dataset(
            dataset,
            user,
            allow_rebuild=allow_rebuild,
            immediate=False,
        )

    async def project_dataset_now(self, dataset: str, user: Any | None, *, allow_rebuild: bool = True) -> None:
        await self._project_dataset(
            dataset,
            user,
            allow_rebuild=allow_rebuild,
            immediate=True,
        )

    async def _project_dataset(
        self,
        dataset: str,
        user: Any | None,
        *,
        allow_rebuild: bool = True,
        immediate: bool = False,
    ) -> None:
        import cognee

        alias = self.dataset_service.alias_for_dataset(dataset)
        user_ctx = self.dataset_service.to_user_ctx(user)
        if user_ctx is None:
            logger.warning(f"knowledge_project_skipped dataset={alias}: user context unavailable")
            return
        if allow_rebuild:
            self.clear_stall(alias)
        if self._is_blocked(alias):
            logger.warning(
                f"projection.skipped dataset={alias} reason=stalled "
                f"cooldown_s={max(float(settings.COGNEE_PROJECTION_STALL_COOLDOWN_S), 0.0):.0f}"
            )
            return
        if not immediate and self._batch_window_s() > 0:
            await self._schedule_projection(dataset, user, allow_rebuild=allow_rebuild)
            return
        if await self._should_debounce_redis(alias) or self._should_debounce(alias):
            self.dataset_service.log_once(
                logging.DEBUG,
                "projection:debounced",
                dataset=alias,
                min_interval=float(settings.COGNEE_PROJECTION_DEBOUNCE_S),
                ttl=float(settings.COGNEE_PROJECTION_DEBOUNCE_S),
            )
            return
        dataset_id = await self.dataset_service.get_dataset_id(alias, user_ctx)
        target = alias

        logger.info(f"projection.start dataset={alias} reason=requested allow_rebuild={allow_rebuild}")

        dataset_uuid = None
        if dataset_id:
            try:
                from uuid import UUID

                dataset_uuid = dataset_id if isinstance(dataset_id, UUID) else UUID(str(dataset_id))
            except Exception:
                dataset_uuid = None
        if dataset_uuid is None:
            dataset_uuid = await self.dataset_service.get_dataset_uuid(alias, user_ctx)
        if dataset_uuid is not None:
            dataset_id = str(dataset_uuid)
            await self.dataset_service.reset_pipeline_status(dataset_uuid, "cognify_pipeline")

        self.dataset_service.log_once(
            logging.DEBUG,
            "projection:cognify_start",
            dataset=alias,
            dataset_id=dataset_id,
            min_interval=5.0,
        )
        start_ts = monotonic()
        max_duration_s = max(float(settings.COGNEE_PROJECTION_MAX_DURATION_S), 0.0)
        attempts = max(int(settings.COGNEE_PROJECTION_RETRY_MAX_ATTEMPTS), 1)
        for attempt in range(1, attempts + 1):
            if max_duration_s and (monotonic() - start_ts) >= max_duration_s:
                cooldown_s = max(float(settings.COGNEE_PROJECTION_STALL_COOLDOWN_S), 0.0)
                state = self._stall_state(alias)
                state["blocked_until"] = monotonic() + cooldown_s
                logger.error(
                    f"projection.stopped dataset={alias} reason=max_duration "
                    f"elapsed_s={monotonic() - start_ts:.1f} cooldown_s={cooldown_s:.0f}"
                )
                return
            try:
                logger.debug(f"projection.cognee_call dataset={alias} target={target} attempt={attempt}/{attempts}")
                async with self._get_cognify_semaphore():
                    result = await cognee.cognify(datasets=[target], user=user_ctx, incremental_loading=True)
                self._register_dataset_uuids(alias, result)
                duration = monotonic() - start_ts
                logger.debug(
                    "projection.cognee_done dataset={} duration={:.2f}s result_type={}",
                    alias,
                    duration,
                    type(result).__name__,
                )
                summary = self._summarize_cognify_result(result)
                if summary is not None:
                    logger.debug(f"projection.cognee_result dataset={alias} detail={summary}")
                break
            except FileNotFoundError as exc:
                if not settings.COGNEE_ENABLE_AGGRESSIVE_REBUILD:
                    logger.warning(
                        f"knowledge_dataset_storage_missing dataset={alias} missing={getattr(exc, 'filename', None)} "
                        "reason=aggressive_rebuild_disabled"
                    )
                    return
                missing_path = getattr(exc, "filename", None) or str(exc)
                logger.debug(f"knowledge_dataset_storage_missing dataset={alias} missing={missing_path}")
                missing, healed = await self.storage_service.heal_dataset_storage(
                    alias, user_ctx, reason="cognify_missing"
                )
                self.dataset_service._PROJECTED_DATASETS.discard(alias)
                if healed > 0:
                    await self.project_dataset_now(alias, user, allow_rebuild=True)
                    return
                self.dataset_service.log_once(
                    logging.WARNING,
                    "storage_missing:heal_failed",
                    dataset=alias,
                    missing=missing,
                    healed=healed,
                    min_interval=30.0,
                )
                self.storage_service.log_storage_state(alias, missing_count=missing, healed_count=healed)
                if allow_rebuild and settings.COGNEE_ENABLE_AGGRESSIVE_REBUILD:
                    kb = self._knowledge_base
                    if kb is not None:
                        await kb.rebuild_dataset(alias, user)
                        logger.debug(f"knowledge_dataset_rebuilt dataset={alias}")
                        await self.project_dataset_now(alias, user, allow_rebuild=True)
                        return
                    else:
                        self.dataset_service.log_once(
                            logging.WARNING,
                            "projection:rebuild_skipped",
                            dataset=alias,
                            reason="knowledge_base_unavailable",
                            min_interval=30.0,
                        )
                raise
            except Exception as exc:
                self._maybe_mark_degraded(exc)
                if attempt < attempts and self._is_retryable_cognify_error(exc):
                    delay = self._retry_delay_s(attempt)
                    logger.debug(
                        "projection.cognify_retry dataset={} attempt={}/{} delay_s={:.2f} error={}",
                        alias,
                        attempt,
                        attempts,
                        delay,
                        type(exc).__name__,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.exception(f"knowledge_dataset_cognify_failed dataset={dataset}")
                raise
        try:
            counts = await self.dataset_service.get_counts(alias, user)
        except Exception as exc:  # noqa: BLE001 - logging-only diagnostics
            logger.debug(f"projection.counts_failed dataset={alias} detail={exc}")
            counts = {}
        duration = monotonic() - start_ts
        logger.info(
            (
                f"projection.done dataset={alias} duration={duration:.2f}s "
                f"text_rows={counts.get('text_rows', 0)} "
                f"chunk_rows={counts.get('chunk_rows', 0)} "
                f"graph_nodes={counts.get('graph_nodes', 0)} "
                f"graph_edges={counts.get('graph_edges', 0)}"
            )
        )
        if self._record_progress(alias, counts):
            logger.error(
                f"projection.stalled dataset={alias} reason=no_progress_runs "
                f"limit={max(int(settings.COGNEE_PROJECTION_STALL_LIMIT), 0)} "
                f"cooldown_s={max(float(settings.COGNEE_PROJECTION_STALL_COOLDOWN_S), 0.0):.0f}"
            )
        self.dataset_service.log_once(
            logging.DEBUG,
            "projection:cognify_done",
            dataset=alias,
            dataset_id=dataset_id,
            min_interval=5.0,
        )

    def _register_dataset_uuids(self, alias: str, result: Any) -> None:
        if not isinstance(result, dict):
            return
        from uuid import UUID

        for value in result.values():
            candidate = getattr(value, "dataset_id", None)
            if not candidate:
                continue
            try:
                dataset_uuid = candidate if isinstance(candidate, UUID) else UUID(str(candidate))
            except Exception:
                continue
            self.dataset_service.register_dataset_identifier(alias, str(dataset_uuid))

    @staticmethod
    def _summarize_cognify_result(result: Any) -> Any:
        if isinstance(result, dict):
            summary: dict[str, Any] = {}
            for key, value in list(result.items())[:5]:
                if hasattr(value, "status"):
                    summary[str(key)] = getattr(value, "status")
                elif hasattr(value, "state"):
                    summary[str(key)] = getattr(value, "state")
                elif hasattr(value, "run_state"):
                    summary[str(key)] = getattr(value, "run_state")
                else:
                    summary[str(key)] = type(value).__name__
            return summary
        return result
