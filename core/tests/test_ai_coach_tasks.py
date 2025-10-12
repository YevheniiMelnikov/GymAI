from typing import Any

import pytest  # pyrefly: ignore[import-error]

from core.tasks import generate_ai_workout_plan, update_ai_workout_plan


@pytest.mark.parametrize("task_obj", [generate_ai_workout_plan, update_ai_workout_plan])
def test_ai_plan_tasks_use_asyncio_run(task_obj, monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, Any] = {}

    async def fake_impl(payload: dict[str, Any], task: Any) -> None:
        called["payload"] = payload
        called["task"] = task

    target_name = (
        "core.tasks._generate_ai_workout_plan_impl"
        if task_obj is generate_ai_workout_plan
        else "core.tasks._update_ai_workout_plan_impl"
    )
    monkeypatch.setattr(target_name, fake_impl)

    def fake_run(coro: Any) -> None:
        called["coro_name"] = coro.cr_code.co_name
        coro.close()

    monkeypatch.setattr("core.tasks.asyncio.run", fake_run)
    payload = {"client_id": 1}
    task_obj.run(payload)
    assert called["payload"] == payload
    assert called["coro_name"] in {"fake_impl", "fake_impl"}
