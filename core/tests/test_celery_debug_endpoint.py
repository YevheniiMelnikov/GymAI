from __future__ import annotations

import json
from typing import Any

import pytest

try:  # pragma: no cover - fallback for environments without kombu installed
    from kombu.exceptions import ChannelError
except ModuleNotFoundError:  # pragma: no cover - test fallback

    class ChannelError(Exception):
        """Fallback ChannelError for test environments."""

        pass


from bot.handlers.internal.debug import (
    internal_celery_debug,
    internal_celery_queue_depth,
    internal_celery_result,
    internal_celery_submit_echo,
)
from config.app_settings import settings


class DummyInspect:
    def __init__(self) -> None:
        self._data: dict[str, Any] = {
            "queues": {"worker@example": [{"name": "ai_coach"}]},
            "registered": {"worker@example": ["core.tasks.generate_ai_workout_plan"]},
            "active": {"worker@example": []},
            "reserved": {"worker@example": []},
            "scheduled": {"worker@example": []},
        }

    def active_queues(self) -> dict[str, Any]:
        return self._data["queues"]

    def registered(self) -> dict[str, Any]:
        return self._data["registered"]

    def active(self) -> dict[str, Any]:
        return self._data["active"]

    def reserved(self) -> dict[str, Any]:
        return self._data["reserved"]

    def scheduled(self) -> dict[str, Any]:
        return self._data["scheduled"]


class DummyRequest:
    def __init__(
        self,
        headers: dict[str, str],
        *,
        query: dict[str, str] | None = None,
        json_payload: Any | None = None,
    ) -> None:
        self.headers = headers
        self.app: dict[str, Any] = {}
        self.query = query or {}
        self._json_payload = json_payload

    async def json(self) -> Any:
        if isinstance(self._json_payload, Exception):
            raise self._json_payload
        if self._json_payload is None:
            raise ValueError("JSON payload not provided")
        return self._json_payload


@pytest.mark.asyncio
async def test_internal_celery_debug_returns_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    inspect = DummyInspect()
    monkeypatch.setattr("bot.handlers.internal.debug.app.control.inspect", lambda: inspect)

    request = DummyRequest({"Authorization": f"Api-Key {settings.API_KEY}"})
    response = await internal_celery_debug(request)  # type: ignore[arg-type]
    assert response.status == 200
    data = json.loads(response.body.decode())
    assert data["active_queues"] == inspect.active_queues()
    assert data["registered"] == inspect.registered()
    assert data["routes"]["core.tasks.generate_ai_workout_plan"]["queue"] == "ai_coach"


@pytest.mark.asyncio
async def test_internal_celery_debug_requires_auth() -> None:
    request = DummyRequest({})
    response = await internal_celery_debug(request)  # type: ignore[arg-type]
    assert response.status == 403
    data = json.loads(response.body.decode())
    assert data["detail"] == "Forbidden"


@pytest.mark.asyncio
async def test_internal_celery_result_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyResult:
        def __init__(self) -> None:
            self.id = "task123"
            self.state = "SUCCESS"
            self._ready = True
            self.result = {"ok": True}
            self.traceback = None

        def ready(self) -> bool:
            return self._ready

        def successful(self) -> bool:
            return True

    monkeypatch.setattr("bot.handlers.internal.debug.AsyncResult", lambda task_id, app=None: DummyResult())

    request = DummyRequest(
        {"Authorization": f"Api-Key {settings.API_KEY}"},
        query={"task_id": "task123"},
    )
    response = await internal_celery_result(request)  # type: ignore[arg-type]
    assert response.status == 200
    payload = json.loads(response.body.decode())
    assert payload["id"] == "task123"
    assert payload["state"] == "SUCCESS"
    assert payload["successful"] is True


@pytest.mark.asyncio
async def test_internal_celery_result_requires_task_id() -> None:
    request = DummyRequest({"Authorization": f"Api-Key {settings.API_KEY}"})
    response = await internal_celery_result(request)  # type: ignore[arg-type]
    assert response.status == 400
    payload = json.loads(response.body.decode())
    assert payload["detail"] == "task_id is required"


@pytest.mark.asyncio
async def test_internal_celery_queue_depth_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyChannel:
        def __init__(self) -> None:
            self.closed = False

        def queue_declare(self, queue: str, passive: bool) -> Any:
            assert passive is True
            assert queue == "ai_coach"
            return type("DeclareResult", (), {"message_count": 5, "consumer_count": 1})()

        def close(self) -> None:
            self.closed = True

    class DummyConnection:
        def __init__(self, url: str) -> None:
            self.url = url

        def __enter__(self) -> "DummyConnection":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        def channel(self) -> DummyChannel:
            return DummyChannel()

    monkeypatch.setattr("bot.handlers.internal.debug.Connection", DummyConnection)
    monkeypatch.setattr("bot.handlers.internal.debug.AI_COACH_QUEUE", type("Q", (), {"name": "ai_coach"})())
    monkeypatch.setattr(
        "bot.handlers.internal.debug.app.conf", "broker_url", "amqp://guest:guest@localhost//", raising=False
    )

    request = DummyRequest({"Authorization": f"Api-Key {settings.API_KEY}"})
    response = await internal_celery_queue_depth(request)  # type: ignore[arg-type]
    assert response.status == 200
    payload = json.loads(response.body.decode())
    assert payload == {"queue": "ai_coach", "messages": 5, "consumers": 1}


@pytest.mark.asyncio
async def test_internal_celery_queue_depth_handles_channel_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingConnection:
        def __init__(self, url: str) -> None:
            self.url = url

        def __enter__(self) -> "FailingConnection":
            raise ChannelError("not found")

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

    monkeypatch.setattr("bot.handlers.internal.debug.Connection", FailingConnection)
    monkeypatch.setattr("bot.handlers.internal.debug.AI_COACH_QUEUE", type("Q", (), {"name": "ai_coach"})())
    monkeypatch.setattr(
        "bot.handlers.internal.debug.app.conf", "broker_url", "amqp://guest:guest@localhost//", raising=False
    )

    request = DummyRequest({"Authorization": f"Api-Key {settings.API_KEY}"})
    response = await internal_celery_queue_depth(request)  # type: ignore[arg-type]
    assert response.status == 500
    payload = json.loads(response.body.decode())
    assert "queue declare failed" in payload["detail"]


@pytest.mark.asyncio
async def test_internal_celery_submit_echo_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class DummyAsyncResult:
        def __init__(self, task_id: str) -> None:
            self.id = task_id

    def _send_task(name: str, args: tuple[Any, ...], queue: str, routing_key: str) -> DummyAsyncResult:
        captured.update({"name": name, "args": args, "queue": queue, "routing_key": routing_key})
        return DummyAsyncResult("echo-task")

    monkeypatch.setattr("bot.handlers.internal.debug.app.send_task", _send_task)

    request = DummyRequest(
        {"Authorization": f"Api-Key {settings.API_KEY}"},
        json_payload={"ping": "pong"},
    )
    response = await internal_celery_submit_echo(request)  # type: ignore[arg-type]
    assert response.status == 202
    payload = json.loads(response.body.decode())
    assert payload["task_id"] == "echo-task"
    assert captured["name"] == "core.tasks.ai_coach_echo"
    assert captured["queue"] == "ai_coach"
    assert captured["routing_key"] == "ai_coach"


@pytest.mark.asyncio
async def test_internal_celery_submit_echo_invalid_payload() -> None:
    request = DummyRequest(
        {"Authorization": f"Api-Key {settings.API_KEY}"},
        json_payload=ValueError("boom"),
    )
    response = await internal_celery_submit_echo(request)  # type: ignore[arg-type]
    assert response.status == 400
    payload = json.loads(response.body.decode())
    assert payload["detail"] == "Invalid JSON"
