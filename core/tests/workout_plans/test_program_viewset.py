import os
from types import SimpleNamespace

import django
import pytest

from apps.workout_plans.views import ProgramViewSet, SubscriptionViewSet

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.test_settings")
django.setup()


def test_program_create_requires_profile() -> None:
    view = ProgramViewSet()
    request = SimpleNamespace(data={"exercises_by_day": []})
    response = view.create(request)  # type: ignore[arg-type]

    assert response.status_code == 400
    assert response.data == {"error": "profile is required"}


def test_program_update_invalidates_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    view = ProgramViewSet()
    view.get_object = lambda: SimpleNamespace(profile_id=10, exercises_by_day=["old"])
    view.get_serializer = lambda *args, **kwargs: SimpleNamespace(
        is_valid=lambda **_: True,
        validated_data={"exercises_by_day": ["new"]},
        data={"id": 1},
    )
    monkeypatch.setattr(
        "apps.workout_plans.views.ProgramRepository.create_or_update",
        lambda profile_id, exercises, instance=None: SimpleNamespace(id=5, profile_id=profile_id),
    )

    request = SimpleNamespace(data={"profile": "10"})
    response = view.update(request, pk=1)  # type: ignore[arg-type]

    assert response.status_code == 200


def test_subscription_update_does_not_touch_cache() -> None:
    serializer = SimpleNamespace(save=lambda: SimpleNamespace(profile_id=7))
    SubscriptionViewSet().perform_update(serializer)  # type: ignore[arg-type]
