from typing import Any

import pytest  # pyrefly: ignore[import-error]

from core.tasks.ai_coach import generate_ai_workout_plan, update_ai_workout_plan


@pytest.mark.parametrize(
    ("task_obj", "target_name"),
    [
        (generate_ai_workout_plan, "core.tasks.ai_coach._generate_ai_workout_plan_impl"),
        (update_ai_workout_plan, "core.tasks.ai_coach._update_ai_workout_plan_impl"),
    ],
)
def test_ai_plan_tasks_notify_on_success(task_obj: Any, target_name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, Any] = {}

    async def fake_impl(payload: dict[str, Any], task: Any) -> dict[str, Any]:
        called["payload"] = payload
        called["task"] = task
        return {"status": "success"}

    monkeypatch.setattr(target_name, fake_impl)

    notified: dict[str, Any] = {"called": False}

    def fake_apply_async(*, args: list[dict[str, Any]], queue: str, routing_key: str) -> None:
        notified["called"] = True
        notified["args"] = args
        notified["queue"] = queue
        notified["routing_key"] = routing_key

    monkeypatch.setattr("core.tasks.ai_coach.notify_ai_plan_ready_task.apply_async", fake_apply_async)

    def fake_run(coro: Any) -> dict[str, Any] | None:
        called["coro_name"] = coro.cr_code.co_name
        try:
            coro.send(None)
        except StopIteration as exc:  # pragma: no cover - defensive
            return exc.value
        return None

    monkeypatch.setattr("core.tasks.ai_coach.asyncio.run", fake_run)
    payload = {"client_id": 1}
    result = task_obj.run(payload)

    assert called["payload"] == payload
    assert called["task"] is task_obj
    assert called["coro_name"] == "fake_impl"
    assert notified["called"] is True
    assert notified["queue"] == "ai_coach"
    assert notified["routing_key"] == "ai_coach"
    assert notified["args"] == [result]
    assert result == {"status": "success"}


@pytest.mark.parametrize(
    ("task_obj", "target_name"),
    [
        (generate_ai_workout_plan, "core.tasks.ai_coach._generate_ai_workout_plan_impl"),
        (update_ai_workout_plan, "core.tasks.ai_coach._update_ai_workout_plan_impl"),
    ],
)
def test_ai_plan_tasks_skip_notify_on_empty_payload(
    task_obj: Any, target_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: dict[str, Any] = {}

    async def fake_impl(payload: dict[str, Any], task: Any) -> None:
        called["payload"] = payload
        called["task"] = task
        return None

    monkeypatch.setattr(target_name, fake_impl)

    notified: dict[str, Any] = {"called": False}

    def fake_apply_async(*, args: list[dict[str, Any]], queue: str, routing_key: str) -> None:
        notified["called"] = True

    monkeypatch.setattr("core.tasks.ai_coach.notify_ai_plan_ready_task.apply_async", fake_apply_async)

    def fake_run(coro: Any) -> None:
        called["coro_name"] = coro.cr_code.co_name
        coro.close()
        return None

    monkeypatch.setattr("core.tasks.ai_coach.asyncio.run", fake_run)
    payload = {"client_id": 1}
    result = task_obj.run(payload)

    assert called["payload"] == payload
    assert called["task"] is task_obj
    assert called["coro_name"] == "fake_impl"
    assert notified["called"] is False
    assert result is None
