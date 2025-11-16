from types import SimpleNamespace

import pytest

from bot.utils.ai_coach import enqueue_workout_plan_generation, enqueue_workout_plan_update
from core.enums import WorkoutPlanType, WorkoutType
from core.schemas import Client


class DummySignature:
    def __init__(self, name: str, payload: dict | None = None, action: str | None = None) -> None:
        self.data = {"name": name, "payload": payload, "action": action}

    def set(self, **options):  # type: ignore[no-untyped-def]
        self.data["options"] = options
        return self


class DummyTask:
    def __init__(self, name: str) -> None:
        self.name = name

    def s(self, payload=None, action=None):  # type: ignore[no-untyped-def]
        return DummySignature(self.name, payload, action)


class DummyChain:
    def __init__(self, signatures, record):  # type: ignore[no-untyped-def]
        self.signatures = signatures
        self.record = record

    def apply_async(self, link_error=None):  # type: ignore[no-untyped-def]
        self.record["signatures"] = [sig.data for sig in self.signatures]
        self.record["link_error"] = [sig.data for sig in (link_error or [])]
        return SimpleNamespace(id="task-123")


@pytest.mark.asyncio
async def test_enqueue_generation_uses_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    record: dict[str, list[dict]] = {}
    monkeypatch.setattr("bot.utils.ai_coach.generate_ai_workout_plan", DummyTask("generate"))
    monkeypatch.setattr("bot.utils.ai_coach.notify_ai_plan_ready_task", DummyTask("notify"))
    monkeypatch.setattr("bot.utils.ai_coach.handle_ai_plan_failure", DummyTask("failure"))
    monkeypatch.setattr("bot.utils.ai_coach.chain", lambda *sigs: DummyChain(sigs, record))

    client = Client(id=5, profile=10)
    ok = await enqueue_workout_plan_generation(
        client=client,
        language="en",
        plan_type=WorkoutPlanType.PROGRAM,
        workout_type=WorkoutType.STRENGTH,
        wishes="focus",
        request_id="req-1",
    )

    assert ok is True
    assert record["signatures"][0]["payload"]["client_profile_id"] == client.profile
    assert record["link_error"][0]["action"] == "create"


@pytest.mark.asyncio
async def test_enqueue_update_uses_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    record: dict[str, list[dict]] = {}
    monkeypatch.setattr("bot.utils.ai_coach.update_ai_workout_plan", DummyTask("update"))
    monkeypatch.setattr("bot.utils.ai_coach.notify_ai_plan_ready_task", DummyTask("notify"))
    monkeypatch.setattr("bot.utils.ai_coach.handle_ai_plan_failure", DummyTask("failure"))
    monkeypatch.setattr("bot.utils.ai_coach.chain", lambda *sigs: DummyChain(sigs, record))

    ok = await enqueue_workout_plan_update(
        client_id=7,
        client_profile_id=11,
        expected_workout_result="result",
        feedback="good",
        language="en",
        plan_type=WorkoutPlanType.SUBSCRIPTION,
        workout_type=None,
        request_id="req-2",
    )

    assert ok is True
    assert record["signatures"][0]["payload"]["client_profile_id"] == 11
    assert record["link_error"][0]["action"] == "update"


@pytest.mark.asyncio
async def test_enqueue_generation_requires_profile() -> None:
    client = Client(id=1, profile=0)
    ok = await enqueue_workout_plan_generation(
        client=client,
        language="en",
        plan_type=WorkoutPlanType.PROGRAM,
        workout_type=WorkoutType.STRENGTH,
        wishes="",
        request_id="req-3",
    )
    assert ok is False
