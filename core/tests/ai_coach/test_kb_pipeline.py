from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase, ProjectionStatus
from ai_coach.agent.knowledge.utils.chat_queue import ChatProjectionScheduler
from ai_coach.agent.knowledge.utils.projection import ProjectionService


@pytest.mark.asyncio
async def test_add_text_skips_empty_content(monkeypatch):
    kb = KnowledgeBase()

    class DummyDatasetService:
        async def get_cognee_user(self) -> object:
            return object()

        def dataset_name(self, client_id: int) -> str:
            return f"kb_client_{client_id}"

        def alias_for_dataset(self, dataset: str) -> str:
            return dataset

        def _normalize_text(self, value: str) -> str:
            return "   "

    dummy_dataset = DummyDatasetService()
    kb.dataset_service = dummy_dataset
    kb.update_dataset = AsyncMock()
    queue_mock = MagicMock()
    kb.chat_queue_service = SimpleNamespace(
        queue_chat_dataset=queue_mock,
        ensure_chat_projection_task=MagicMock(),
    )

    await kb.add_text("   ", dataset="kb_global", project=False)

    kb.update_dataset.assert_not_called()
    queue_mock.assert_not_called()


@pytest.mark.asyncio
async def test_projection_ready_empty_marks_dataset(monkeypatch):
    class DummyDatasetService:
        def __init__(self) -> None:
            self.projected: set[str] = set()

        def alias_for_dataset(self, dataset: str) -> str:
            return dataset

        def to_user_ctx(self, user: object) -> object:
            return user

        async def ensure_dataset_exists(self, alias: str, user_ctx: object) -> None:
            return None

        def add_projected_dataset(self, alias: str) -> None:
            self.projected.add(alias)

    dataset_service = DummyDatasetService()
    storage_service = MagicMock()
    service = ProjectionService(dataset_service, storage_service)
    monkeypatch.setattr(service, "probe", AsyncMock(return_value=(False, "no_rows_in_dataset")))

    status = await service.ensure_dataset_projected("kb_global", user=SimpleNamespace(id="user"))

    assert status == ProjectionStatus.READY_EMPTY
    assert "kb_global" in dataset_service.projected


@pytest.mark.asyncio
async def test_chat_projection_scheduler_uses_kb_user(monkeypatch):
    class DummyDatasetService:
        async def get_cognee_user(self) -> object:
            return object()

        def alias_for_dataset(self, dataset: str) -> str:
            return dataset

    class DummyKB:
        def __init__(self) -> None:
            self._user = object()
            self._process_dataset = AsyncMock()

        @staticmethod
        def _log_task_exception(task: object) -> None:  # pragma: no cover - scheduler contract
            return None

    ChatProjectionScheduler._CHAT_PENDING.clear()
    ChatProjectionScheduler._CHAT_PROJECT_TASKS.clear()
    ChatProjectionScheduler._CHAT_LAST_PROJECT_TS.clear()

    kb = DummyKB()
    dataset_service = DummyDatasetService()
    scheduler = ChatProjectionScheduler(dataset_service, kb)
    alias = "kb_chat_99"
    scheduler._CHAT_PENDING[alias] = 1

    await scheduler._run_chat_projection(alias, 0.0)

    kb._process_dataset.assert_awaited_once_with(alias, kb._user)
