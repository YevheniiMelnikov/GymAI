from __future__ import annotations

import json
from typing import Any

import pytest

from bot.handlers.internal.debug import internal_celery_debug
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
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers
        self.app: dict[str, Any] = {}


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
