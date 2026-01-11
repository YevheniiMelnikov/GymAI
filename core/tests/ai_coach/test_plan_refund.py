import importlib
from types import SimpleNamespace
from typing import Any

import pytest  # pyrefly: ignore[import-error]

from config import app_settings as app_settings_module
from core.enums import WorkoutPlanType


class _SettingsStub(SimpleNamespace):
    def __getattr__(self, name: str) -> Any:  # pragma: no cover - fallback for typed attrs
        if name.endswith(("_TIMEOUT", "_TTL", "_DAYS")):
            return 0
        return "stub"


_REQUIRED_SETTINGS: dict[str, Any] = {
    "RABBITMQ_URL": "amqp://guest:guest@localhost:5672//",
    "AI_COACH_TIMEOUT": 300,
    "AI_PLAN_NOTIFY_TIMEOUT": 120,
    "AI_PLAN_DEDUP_TTL": 3600,
    "AI_PLAN_NOTIFY_FAILURE_TTL": 3600,
    "AI_PROGRAM_PRICE": 400,
    "SMALL_SUBSCRIPTION_PRICE": 500,
    "MEDIUM_SUBSCRIPTION_PRICE": 2400,
    "LARGE_SUBSCRIPTION_PRICE": 4750,
    "DB_NAME": "db",
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "DB_USER": "user",
    "REDIS_URL": "redis://localhost:6379/0",
    "BACKUP_RETENTION_DAYS": 7,
    "BOT_INTERNAL_URL": "http://bot:8000/",
    "API_KEY": "api",
    "INTERNAL_API_KEY": "internal",
    "INTERNAL_KEY_ID": "internal",
    "INTERNAL_HTTP_CONNECT_TIMEOUT": 5.0,
    "INTERNAL_HTTP_READ_TIMEOUT": 10.0,
    "API_TIMEOUT": 10,
}


@pytest.fixture(name="ai_coach_context")
def ai_coach_context_fixture(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    settings = _SettingsStub(**_REQUIRED_SETTINGS)
    monkeypatch.setattr(app_settings_module, "settings", settings, raising=False)
    module = importlib.reload(importlib.import_module("core.tasks.ai_coach"))
    module.plans.settings = settings
    yield SimpleNamespace(tasks=module, settings=settings)
    importlib.reload(importlib.import_module("core.tasks.ai_coach"))


@pytest.fixture(name="ai_coach_tasks")
def ai_coach_tasks_fixture(ai_coach_context: SimpleNamespace):
    return ai_coach_context.tasks


@pytest.mark.asyncio
async def test_refund_plan_credits_marks_refunded(ai_coach_tasks, monkeypatch: pytest.MonkeyPatch) -> None:
    async def is_refunded(_: str) -> bool:
        return False

    async def claim_refund(_: str, ttl_s: int | None = None) -> bool:
        return True

    mark_calls: dict[str, Any] = {"count": 0}

    async def mark_refunded(_: str, ttl_s: int | None = None) -> bool:
        mark_calls["count"] += 1
        return True

    async def release_refund_lock(_: str) -> None:
        return None

    state = SimpleNamespace(
        is_refunded=is_refunded,
        claim_refund=claim_refund,
        mark_refunded=mark_refunded,
        release_refund_lock=release_refund_lock,
    )

    monkeypatch.setattr(ai_coach_tasks.plans, "AiPlanState", SimpleNamespace(create=lambda: state))

    adjust_calls: dict[str, Any] = {"values": []}

    async def adjust_credits(profile_id: int, delta: int) -> None:
        adjust_calls["values"].append((profile_id, delta))

    monkeypatch.setattr(
        ai_coach_tasks.plans,
        "APIService",
        SimpleNamespace(profile=SimpleNamespace(adjust_credits=adjust_credits)),
    )

    payload = {"request_id": "req-1", "plan_type": "program"}
    await ai_coach_tasks.plans._refund_plan_credits(
        payload,
        profile_id=42,
        request_id="req-1",
        plan_type=WorkoutPlanType.PROGRAM,
    )

    assert adjust_calls["values"] == [(42, 400)]
    assert mark_calls["count"] == 1
