import asyncio
from time import monotonic
from typing import Any, ClassVar, TYPE_CHECKING

from loguru import logger

from ai_coach.agent.knowledge.utils.datasets import DatasetService
from config.app_settings import settings

if TYPE_CHECKING:
    from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase


class ChatProjectionScheduler:
    _CHAT_PENDING: ClassVar[dict[str, int]] = {}
    _CHAT_PROJECT_TASKS: ClassVar[dict[str, asyncio.Task[Any]]] = {}
    _CHAT_LAST_PROJECT_TS: ClassVar[dict[str, float]] = {}

    def __init__(self, dataset_service: DatasetService, knowledge_base: "KnowledgeBase") -> None:
        self.dataset_service = dataset_service
        self._knowledge_base = knowledge_base

    def queue_chat_dataset(self, alias: str) -> int:
        normalized = self.dataset_service.alias_for_dataset(alias)
        pending = self._CHAT_PENDING.get(normalized, 0) + 1
        self._CHAT_PENDING[normalized] = pending
        return pending

    def _chat_debounce_seconds(self) -> float:
        raw_minutes = float(settings.KB_CHAT_PROJECT_DEBOUNCE_MIN)
        return max(raw_minutes, 0.0) * 60.0

    def _chat_projection_delay(self, alias: str) -> float:
        debounce = self._chat_debounce_seconds()
        if debounce <= 0:
            return 0.0
        last = self._CHAT_LAST_PROJECT_TS.get(alias, 0.0)
        now = monotonic()
        if last <= 0:
            return 0.0
        remaining = (last + debounce) - now
        return remaining if remaining > 0 else 0.0

    def ensure_chat_projection_task(self, alias: str) -> None:
        normalized = self.dataset_service.alias_for_dataset(alias)
        if self._CHAT_PENDING.get(normalized, 0) <= 0:
            return
        existing = self._CHAT_PROJECT_TASKS.get(normalized)
        if existing and not existing.done():
            return
        delay = self._chat_projection_delay(normalized)
        task = asyncio.create_task(self._run_chat_projection(normalized, delay))
        self._CHAT_PROJECT_TASKS[normalized] = task
        task.add_done_callback(self._knowledge_base._log_task_exception)

    async def _run_chat_projection(self, alias: str, delay: float) -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        queued = self._CHAT_PENDING.get(alias, 0)
        if queued <= 0:
            self._CHAT_PROJECT_TASKS.pop(alias, None)
            return
        logger.debug(f"kb_chat_project start queued={queued} dataset={alias}")
        kb_user = getattr(self._knowledge_base, "_user", None)
        started = monotonic()
        try:
            await self._knowledge_base._process_dataset(alias, kb_user)
        except Exception as exc:
            logger.warning(f"kb_chat_project failed dataset={alias} queued={queued} detail={exc}")
            self._CHAT_PROJECT_TASKS.pop(alias, None)
            self._CHAT_LAST_PROJECT_TS[alias] = monotonic()
            self.ensure_chat_projection_task(alias)
            return
        took_ms = int((monotonic() - started) * 1000)
        logger.debug(f"kb_chat_project end queued={queued} dataset={alias} took_ms={took_ms}")
        self._CHAT_PENDING.pop(alias, None)
        self._CHAT_PROJECT_TASKS.pop(alias, None)
        self._CHAT_LAST_PROJECT_TS[alias] = monotonic()
