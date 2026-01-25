import asyncio
import json
import sys
from datetime import date, datetime, timezone
from importlib import import_module
from types import SimpleNamespace
from typing import cast

import pytest
from django.http import HttpRequest, JsonResponse

from apps.webapp import utils


django_http = sys.modules["django.http"]
django_http.HttpResponse = object  # type: ignore[attr-defined]
django_shortcuts = sys.modules.setdefault("django.shortcuts", SimpleNamespace(render=lambda *a, **k: None))

views = import_module("apps.webapp.views")


def test_weekly_survey_submit_updates_sets(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        updated_payload: dict[str, object] = {}
        updated_cache: dict[str, object] = {}
        captured_feedback: dict[str, str] = {}
        stored_snapshots: list[dict[str, object]] = []

        async def noop_ready() -> None:
            return None

        class FakeQS:
            def __init__(self, subscription: object) -> None:
                self._subscription = subscription

            def filter(self, **_kwargs) -> "FakeQS":
                return self

            def order_by(self, *_args) -> "FakeQS":
                return self

            def first(self) -> object | None:
                return self._subscription

        async def fake_cache_update(_profile_id: int, updates: dict) -> None:
            updated_cache.update(updates)

        monkeypatch.setattr(utils, "ensure_container_ready", noop_ready)
        monkeypatch.setattr(views, "ensure_container_ready", noop_ready)
        monkeypatch.setattr("apps.webapp.utils.verify_init_data", lambda _d: {"user": {"id": 1}})
        monkeypatch.setattr(
            utils.ProfileRepository,
            "get_by_telegram_id",
            lambda _tg_id: SimpleNamespace(
                id=1,
                tg_id=123,
                language="ru",
                status="completed",
                workout_goals="strength",
                workout_experience="intermediate",
            ),
        )
        monkeypatch.setattr(
            utils.ProfileRepository,
            "get_by_profile_id",
            lambda _id: SimpleNamespace(id=1),
        )
        subscription = SimpleNamespace(
            id=7,
            enabled=True,
            updated_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            workout_location="gym",
            exercises=[
                {
                    "day": "Day 1",
                    "exercises": [
                        {"name": "Squat", "sets": "3", "reps": "10"},
                    ],
                }
            ],
        )
        monkeypatch.setattr(views.SubscriptionRepository, "base_qs", lambda: FakeQS(subscription))

        def fake_update_exercises(_profile_id: int, exercises: object, instance: object) -> object:
            updated_payload["exercises"] = exercises
            return instance

        monkeypatch.setattr(views.SubscriptionRepository, "update_exercises", fake_update_exercises)
        monkeypatch.setattr(views.Cache.workout, "update_subscription", fake_cache_update)
        monkeypatch.setattr(
            views,
            "enqueue_subscription_update",
            lambda **kwargs: captured_feedback.update({"feedback": str(kwargs.get("feedback", ""))}) or True,
        )
        monkeypatch.setattr(views, "resolve_progress_week_start", lambda: date(2025, 1, 6))
        monkeypatch.setattr(
            views.SubscriptionProgressSnapshotRepository,
            "upsert_week_snapshot",
            lambda **kwargs: stored_snapshots.append(cast(dict[str, object], kwargs.get("payload", {}))),
        )
        monkeypatch.setattr(
            views.SubscriptionProgressSnapshotRepository,
            "get_recent_payloads",
            lambda *_args, **_kwargs: list(stored_snapshots),
        )
        monkeypatch.setattr(
            views.SubscriptionProgressSnapshotRepository,
            "trim_old",
            lambda *_args, **_kwargs: 0,
        )
        monkeypatch.setattr(
            views, "build_internal_hmac_auth_headers", lambda **_kwargs: (_ for _ in ()).throw(Exception("skip"))
        )

        request: HttpRequest = HttpRequest()
        request.method = "POST"
        request.GET = {"init_data": "data"}
        payload = {
            "subscription_id": 7,
            "days": [
                {
                    "id": "day-1",
                    "title": "Day 1",
                    "skipped": False,
                    "exercises": [
                        {
                            "id": "ex-1-0",
                            "name": "Squat",
                            "difficulty": 60,
                            "comment": "felt heavy",
                            "sets_detail": [
                                {"reps": 10, "weight": 50, "weight_unit": "kg"},
                                {"reps": 12, "weight": 55, "weight_unit": "kg"},
                            ],
                        }
                    ],
                }
            ],
        }
        request._body = json.dumps(payload).encode("utf-8")

        response: JsonResponse = await views.weekly_survey_submit(request)
        assert response.status_code == 200
        assert updated_payload["exercises"][0]["exercises"][0]["sets_detail"] == [
            {"reps": 10, "weight": 50.0, "weight_unit": "kg"},
            {"reps": 12, "weight": 55.0, "weight_unit": "kg"},
        ]
        assert updated_payload["exercises"][0]["exercises"][0]["sets"] == "2"
        assert updated_payload["exercises"][0]["exercises"][0]["reps"] == "10-12"
        assert updated_payload["exercises"][0]["exercises"][0]["weight"] == "50-55 kg"
        assert "exercises" in updated_cache
        assert "Progress history" in captured_feedback.get("feedback", "")
        assert "Squat" in captured_feedback.get("feedback", "")

    asyncio.run(runner())
