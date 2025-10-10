import time
import types
from types import SimpleNamespace

import pytest  # pyrefly: ignore[import-error]

from core.enums import WorkoutPlanType
from core.schemas import Program
from core.services.internal.api_client import APIClientTransportError
from core.tasks import _generate_ai_workout_plan_impl, _recover_plan_after_timeout


@pytest.mark.asyncio
async def test_recover_plan_after_timeout_returns_recent_program(monkeypatch: pytest.MonkeyPatch) -> None:
    program = Program(
        id=1,
        client_profile=1,
        exercises_by_day=[],
        created_at=time.time(),
        split_number=1,
        workout_type="gym",
    )

    async def fake_get_latest_program(client_profile_id: int) -> Program | None:
        assert client_profile_id == 1
        return program

    api_service = SimpleNamespace(
        ai_coach=SimpleNamespace(),
        workout=SimpleNamespace(
            get_latest_program=fake_get_latest_program,
            get_latest_subscription=lambda *_args, **_kwargs: None,
        ),
    )
    monkeypatch.setattr("core.tasks.APIService", api_service)

    recovered = await _recover_plan_after_timeout(
        client_profile_id=1,
        plan_type=WorkoutPlanType.PROGRAM,
        started_at=time.time() - 1,
    )

    assert recovered is program


@pytest.mark.asyncio
async def test_recover_plan_after_timeout_ignores_stale_program(monkeypatch: pytest.MonkeyPatch) -> None:
    program = Program(
        id=2,
        client_profile=1,
        exercises_by_day=[],
        created_at=time.time() - 120,
        split_number=1,
        workout_type="gym",
    )

    async def fake_get_latest_program(client_profile_id: int) -> Program | None:
        assert client_profile_id == 1
        return program

    api_service = SimpleNamespace(
        ai_coach=SimpleNamespace(),
        workout=SimpleNamespace(
            get_latest_program=fake_get_latest_program,
            get_latest_subscription=lambda *_args, **_kwargs: None,
        ),
    )
    monkeypatch.setattr("core.tasks.APIService", api_service)

    recovered = await _recover_plan_after_timeout(
        client_profile_id=1,
        plan_type=WorkoutPlanType.PROGRAM,
        started_at=time.time(),
    )

    assert recovered is None


@pytest.mark.asyncio
async def test_generate_plan_recovers_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    program = Program(
        id=3,
        client_profile=1,
        exercises_by_day=[],
        created_at=time.time(),
        split_number=1,
        workout_type="gym",
    )

    async def fake_create_workout_plan(*_args: object, **_kwargs: object) -> Program:
        raise APIClientTransportError("timeout")

    async def fake_get_latest_program(_client_profile_id: int) -> Program | None:
        return program

    captured: dict[str, object] = {}

    async def fake_notify(payload: dict[str, object]) -> None:
        captured.update(payload)

    async def fake_claim(*_args: object, **_kwargs: object) -> bool:
        return True

    api_service = SimpleNamespace(
        ai_coach=SimpleNamespace(create_workout_plan=fake_create_workout_plan),
        workout=SimpleNamespace(
            get_latest_program=fake_get_latest_program,
            get_latest_subscription=lambda *_args, **_kwargs: None,
        ),
    )
    monkeypatch.setattr("core.tasks.APIService", api_service)
    monkeypatch.setattr("core.tasks._notify_ai_plan_ready", fake_notify)
    monkeypatch.setattr("core.tasks._claim_plan_request", fake_claim)

    task = types.SimpleNamespace(request=types.SimpleNamespace(retries=0), max_retries=0)
    payload = {
        "client_id": 1,
        "client_profile_id": 1,
        "request_id": "req-1",
        "plan_type": WorkoutPlanType.PROGRAM.value,
        "language": "ru",
        "period": None,
        "workout_days": ["Mon"],
        "wishes": "",
        "workout_type": None,
    }

    await _generate_ai_workout_plan_impl(payload, task)

    assert captured["status"] == "success"
    assert captured["plan"]["id"] == program.id
