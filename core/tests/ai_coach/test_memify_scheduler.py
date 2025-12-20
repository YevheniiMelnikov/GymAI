import importlib
from types import SimpleNamespace
from typing import Any

import pytest

from ai_coach.agent.knowledge.utils import memify_scheduler
from ai_coach.agent.knowledge import knowledge_base as kb_module


class _DummyRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True


class _DummyTask:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, float]] = []

    def apply_async(self, kwargs=None, countdown: float | None = None):
        self.calls.append((kwargs or {}, float(countdown or 0.0)))


@pytest.mark.asyncio
async def test_schedule_profile_memify_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    dummy_redis = _DummyRedis()
    dummy_task = _DummyTask()
    monkeypatch.setattr(memify_scheduler, "get_redis_client", lambda: dummy_redis)
    monkeypatch.setattr("core.tasks.ai_coach.maintenance.memify_profile_datasets", dummy_task)

    scheduled_first = await memify_scheduler.schedule_profile_memify(7, reason="test", delay_s=5)
    scheduled_second = await memify_scheduler.schedule_profile_memify(7, reason="test", delay_s=5)

    assert scheduled_first is True
    assert scheduled_second is False
    assert dummy_task.calls == [({"profile_id": 7, "reason": "test"}, 5.0)]


@pytest.mark.asyncio
async def test_memify_global_skipped_outside_production(monkeypatch: pytest.MonkeyPatch) -> None:
    kb_module_reloaded = importlib.reload(kb_module)
    KnowledgeBase = kb_module_reloaded.KnowledgeBase
    kb = KnowledgeBase.__new__(KnowledgeBase)

    class DummyDS:
        GLOBAL_DATASET = "kb_global"

        def alias_for_dataset(self, dataset: str) -> str:
            return dataset

        def to_user_ctx(self, user: Any | None) -> Any | None:  # type: ignore[name-defined]
            return user

        async def ensure_dataset_exists(self, alias: str, user: Any | None) -> None:  # type: ignore[name-defined]
            return None

        async def get_dataset_id(self, alias: str, user: Any | None) -> str | None:  # type: ignore[name-defined]
            return None

    kb.dataset_service = DummyDS()
    kb.GLOBAL_DATASET = "kb_global"

    memify_calls: list[tuple[list[str], SimpleNamespace]] = []

    async def fake_memify(datasets, user=None):
        memify_calls.append((datasets, user))

    monkeypatch.setattr(
        "ai_coach.agent.knowledge.knowledge_base.cognee",
        SimpleNamespace(memify=fake_memify),
    )
    monkeypatch.setattr(
        "ai_coach.agent.knowledge.knowledge_base.settings",
        SimpleNamespace(ENVIRONMENT="development"),
    )

    await kb._memify_global_dataset(SimpleNamespace(id=1, tenant_id=None))
    assert memify_calls == []

    monkeypatch.setattr(
        "ai_coach.agent.knowledge.knowledge_base.settings",
        SimpleNamespace(ENVIRONMENT="production"),
    )
    await kb._memify_global_dataset(SimpleNamespace(id=1, tenant_id=None))
    assert memify_calls and memify_calls[0][0] == ["kb_global"]
