import logging
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar, Optional, TYPE_CHECKING

from loguru import logger

from ai_coach.agent.knowledge.schemas import ProjectionStatus
from ai_coach.agent.knowledge.utils.datasets import DatasetService
from ai_coach.agent.knowledge.utils.storage import StorageService
from config.app_settings import settings

if TYPE_CHECKING:
    from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase

Waiter = Callable[..., Awaitable[ProjectionStatus]]


class ProjectionService:
    _MAX_REBUILD_ATTEMPTS: ClassVar[int] = 3

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

    def record_wait_attempts(self, dataset: str, attempts: int, status: ProjectionStatus) -> None:
        alias = self.dataset_service.alias_for_dataset(dataset)
        logger.debug(f"projection.wait dataset={alias} attempts={attempts} status={status.name.lower()}")

    async def ensure_dataset_projected(
        self, dataset: str, user: Any | None, *, timeout_s: float | None = None
    ) -> ProjectionStatus:
        alias = self.dataset_service.alias_for_dataset(dataset)
        user_ctx = self.dataset_service.to_user_ctx(user)

        if user_ctx is None:
            logger.warning(f"knowledge_projection_skipped dataset={alias} reason=user_context_unavailable")
            return ProjectionStatus.USER_CONTEXT_UNAVAILABLE

        wait_timeout = timeout if timeout is not None else 20.0
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

        if not rows:
            self.dataset_service.log_once(
                logging.INFO,
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
        import cognee

        alias = self.dataset_service.alias_for_dataset(dataset)
        user_ctx = self.dataset_service.to_user_ctx(user)
        if user_ctx is None:
            logger.warning(f"knowledge_project_skipped dataset={alias}: user context unavailable")
            return
        dataset_id = await self.dataset_service.get_dataset_id(alias, user_ctx)
        target = dataset_id or alias
        self.dataset_service.log_once(
            logging.DEBUG,
            "projection:cognify_start",
            dataset=alias,
            dataset_id=dataset_id,
            min_interval=5.0,
        )
        try:
            await cognee.cognify(datasets=[target], user=user_ctx)
        except FileNotFoundError as exc:
            if not settings.COGNEE_ENABLE_AGGRESSIVE_REBUILD:
                logger.warning(
                    f"knowledge_dataset_storage_missing dataset={alias} missing={getattr(exc, 'filename', None)} "
                    "reason=aggressive_rebuild_disabled"
                )
                return
            missing_path = getattr(exc, "filename", None) or str(exc)
            logger.debug(f"knowledge_dataset_storage_missing dataset={alias} missing={missing_path}")
            missing, healed = await self.storage_service.heal_dataset_storage(alias, user_ctx, reason="cognify_missing")
            self.dataset_service._PROJECTED_DATASETS.discard(alias)
            if healed > 0:
                await self.project_dataset(alias, user, allow_rebuild=True)
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
                    result = await kb.rebuild_dataset(alias, user)
                    logger.info(f"knowledge_dataset_rebuilt dataset={alias}")
                    await self.project_dataset(alias, user, allow_rebuild=True)
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
            logger.warning(f"knowledge_dataset_cognify_failed dataset={dataset} detail={exc}")
            raise
        self.dataset_service.log_once(
            logging.DEBUG,
            "projection:cognify_done",
            dataset=alias,
            dataset_id=dataset_id,
            min_interval=5.0,
        )
