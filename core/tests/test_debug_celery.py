from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("celery")

from core.debug_celery import trace_publish


class DummyInspect:
    def active_queues(self) -> dict[str, Any]:
        return {"worker@example": [{"name": "ai_coach"}]}

    def registered(self) -> dict[str, Any]:
        return {"worker@example": ["core.tasks.generate_ai_workout_plan"]}


class DummyResult:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


class DummyApp:
    def __init__(self) -> None:
        self.conf = SimpleNamespace(
            broker_url="amqp://guest:guest@localhost//",
            result_backend="redis://localhost/0",
        )
        self.control = SimpleNamespace(inspect=lambda: DummyInspect())
        self.sent: dict[str, Any] | None = None

    def send_task(
        self,
        name: str,
        *,
        args: tuple[Any, ...],
        queue: str,
        routing_key: str,
    ) -> DummyResult:
        self.sent = {
            "name": name,
            "args": args,
            "queue": queue,
            "routing_key": routing_key,
        }
        return DummyResult("trace-task")


class DummyChannel:
    def __init__(self) -> None:
        self.declare_calls = 0
        self.closed = False

    def queue_declare(self, queue: str, passive: bool) -> Any:
        self.declare_calls += 1
        assert passive is True
        return SimpleNamespace(message_count=0, consumer_count=1)

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


class DummyProducer:
    def __init__(self, channel: DummyChannel, exchange: Any, on_return=None) -> None:
        self.channel = channel
        self.exchange = exchange
        self.on_return = on_return
        self.published: list[dict[str, Any]] = []

    def publish(
        self,
        body: dict[str, Any],
        *,
        routing_key: str,
        declare: list[Any],
        mandatory: bool,
        retry: bool,
        retry_policy: dict[str, Any],
    ) -> None:
        assert mandatory is True
        assert retry is True
        self.published.append(
            {
                "body": body,
                "routing_key": routing_key,
                "declare": declare,
                "retry_policy": retry_policy,
            }
        )


def test_trace_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    app = DummyApp()
    monkeypatch.setattr("core.debug_celery.Connection", DummyConnection)
    monkeypatch.setattr("core.debug_celery.Producer", DummyProducer)

    task_id = trace_publish(
        app,  # type: ignore[arg-type]
        queue_name="ai_coach",
        exchange_name="default",
        routing_key="ai_coach",
        task_name="core.tasks.ai_coach_echo",
        payload={"smoke": True},
    )

    assert task_id == "trace-task"
    assert app.sent is not None
    assert app.sent["queue"] == "ai_coach"
    assert app.sent["routing_key"] == "ai_coach"
    assert app.sent["args"] == ({"smoke": True},)
