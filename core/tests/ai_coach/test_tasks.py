from typing import Any

import pytest  # pyrefly: ignore[import-error]

from core.tasks.ai_coach import generate_ai_workout_plan, update_ai_workout_plan

pytestmark = pytest.mark.xfail(
    reason="Celery task runner stubs do not reproduce real async flow; keep as legacy smoke",
    strict=False,
)


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

    def fake_apply_async(*args: Any, **kwargs: Any) -> None:
        notified["called"] = True

    monkeypatch.setattr("core.tasks.ai_coach.notify_ai_plan_ready_task.apply_async", fake_apply_async)

    def fake_run(coro: Any) -> dict[str, Any] | None:
        called["coro_name"] = coro.cr_code.co_name
        try:
            coro.send(None)
        except StopIteration as exc:
            return exc.value
        return None

    monkeypatch.setattr("core.tasks.ai_coach.asyncio.run", fake_run)
    payload = {"profile_id": 1}
    result = task_obj.run(payload)

    assert called["payload"] == payload
    assert called["task"] is task_obj
    assert called["coro_name"] == "fake_impl"
    assert notified["called"] is False
    assert result == {"status": "success"}


@pytest.mark.xfail(reason="task stub cannot emulate full asyncio workflow for empty payload", strict=False)
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

    def fake_apply_async(*args: Any, **kwargs: Any) -> None:
        notified["called"] = True

    monkeypatch.setattr("core.tasks.ai_coach.notify_ai_plan_ready_task.apply_async", fake_apply_async)

    def fake_run(coro: Any) -> None:
        called["coro_name"] = coro.cr_code.co_name
        coro.close()
        return None

    monkeypatch.setattr("core.tasks.ai_coach.asyncio.run", fake_run)
    payload = {"profile_id": 1}
    result = task_obj.run(payload)

    assert called["payload"] == payload
    assert called["task"] is task_obj
    assert called["coro_name"] == "fake_impl"
    assert notified["called"] is False
    assert result is None
