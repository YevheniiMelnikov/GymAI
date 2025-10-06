from __future__ import annotations

from typing import Any

import pytest

from core import queues


def test_ensure_ai_coach_queue_skips_without_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _connection(_: str) -> None:
        calls.append("called")
        raise AssertionError("Connection should not be established without broker URL")

    monkeypatch.setattr(queues, "Connection", _connection)
    monkeypatch.setattr(queues.app.conf, "broker_url", "", raising=False)

    queues.ensure_ai_coach_queue()

    assert calls == []


def test_ensure_ai_coach_queue_declares(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class DummyConnection:
        def __init__(self, url: str) -> None:
            self.url = url
            calls.append(f"init:{url}")

        def __enter__(self) -> "DummyConnection":
            calls.append("enter")
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            calls.append("exit")

    class DummyQueue:
        name = "ai_coach"
        routing_key = "ai_coach"

        def __call__(self, connection: DummyConnection) -> "DummyQueue":
            calls.append(f"bind:{connection.url}")
            return self

        def declare(self) -> None:
            calls.append("declare")

    monkeypatch.setattr(queues, "Connection", DummyConnection)
    monkeypatch.setattr(queues, "AI_COACH_QUEUE", DummyQueue())
    monkeypatch.setattr(queues.app.conf, "broker_url", "amqp://guest:guest@localhost//", raising=False)

    queues.ensure_ai_coach_queue()

    assert calls == [
        "init:amqp://guest:guest@localhost//",
        "enter",
        "bind:amqp://guest:guest@localhost//",
        "declare",
        "exit",
    ]
