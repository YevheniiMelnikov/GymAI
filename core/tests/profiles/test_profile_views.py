import os
import sys
from types import SimpleNamespace

import django
import pytest
from apps.profiles.choices import ProfileStatus
from apps.profiles.views import ProfileAPIList, ProfileAPIDestroy

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.test_settings")
django.setup()


class _SerializerStub:
    def __init__(self, *, validated_data: dict | None = None, data: dict | None = None) -> None:
        self.validated_data = validated_data or {}
        self.data = data or {}

    def is_valid(self, *, raise_exception: bool = False) -> bool:
        return True


class _ProfileStub:
    def __init__(self) -> None:
        self.id = 10
        self.tg_id = 42
        self.status = ProfileStatus.deleted
        self.deleted_at = "deleted"
        self.language = None
        self.gift_credits_granted = False
        self.saved_fields: list[str] = []

    def save(self, *, update_fields: list[str]) -> None:
        self.saved_fields = list(update_fields)


class _QuerySetStub:
    def __init__(self, profile: _ProfileStub) -> None:
        self._profile = profile

    def first(self) -> _ProfileStub:
        return self._profile


class _ManagerStub:
    def __init__(self, profile: _ProfileStub) -> None:
        self._profile = profile

    def filter(self, **kwargs) -> _QuerySetStub:
        return _QuerySetStub(self._profile)


def test_profile_create_restores_deleted(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = _ProfileStub()
    manager = _ManagerStub(profile)
    serializer = _SerializerStub(validated_data={"tg_id": 42, "language": "uk"})

    def fake_get_serializer(*args, **kwargs) -> _SerializerStub:
        if "data" in kwargs:
            return serializer
        instance = args[0] if args else None
        return _SerializerStub(data={"id": getattr(instance, "id", None)})

    enqueue_calls: list[tuple[int, str]] = []

    def fake_enqueue(profile_id: int, *, reason: str) -> None:
        enqueue_calls.append((profile_id, reason))

    monkeypatch.setattr("apps.profiles.models.Profile.objects", manager)
    monkeypatch.setattr(ProfileAPIList, "get_serializer", fake_get_serializer)
    monkeypatch.setattr("apps.profiles.views.ProfileRepository.invalidate_cache", lambda **_: None)
    monkeypatch.setattr(ProfileAPIList, "_enqueue_profile_init", staticmethod(fake_enqueue))

    request = SimpleNamespace(data={"tg_id": 42, "language": "uk"})
    response = ProfileAPIList().create(request)  # type: ignore[arg-type]

    assert response.status_code == 201
    assert profile.status == ProfileStatus.created
    assert profile.deleted_at is None
    assert profile.gift_credits_granted is True
    assert profile.language == "uk"
    assert enqueue_calls == [(profile.id, "profile_restored")]


def test_profile_destroy_soft_deletes_and_enqueues(monkeypatch: pytest.MonkeyPatch) -> None:
    cleanup_calls: list[tuple[int, str]] = []

    def fake_cleanup(profile_id: int, *, reason: str) -> None:
        cleanup_calls.append((profile_id, reason))

    class _DelayStub:
        def __call__(self, profile_id: int, *, reason: str) -> None:
            fake_cleanup(profile_id, reason=reason)

    class _CleanupTask:
        delay = _DelayStub()

    monkeypatch.setattr("apps.profiles.views.ProfileRepository.invalidate_cache", lambda **_: None)
    monkeypatch.setitem(
        sys.modules,
        "core.tasks.ai_coach.maintenance",
        SimpleNamespace(cleanup_profile_knowledge=_CleanupTask()),
    )
    monkeypatch.setattr("apps.profiles.views.timezone.now", lambda: "now")

    class _ProfileDeleteStub:
        def __init__(self) -> None:
            self.pk = 7
            self.tg_id = 11
            self.status = ProfileStatus.created
            self.deleted_at = None
            self.gift_credits_granted = False
            self.gender = "m"
            self.born_in = 1990
            self.weight = 80
            self.height = 180
            self.health_notes = "notes"
            self.workout_experience = "beginner"
            self.workout_goals = "goal"
            self.workout_location = "gym"
            self.saved_fields: list[str] = []

        def save(self, *, update_fields: list[str]) -> None:
            self.saved_fields = list(update_fields)

    profile = _ProfileDeleteStub()

    ProfileAPIDestroy().perform_destroy(profile)

    assert profile.status == ProfileStatus.deleted
    assert profile.deleted_at == "now"
    assert profile.gift_credits_granted is True
    assert profile.gender is None
    assert profile.born_in is None
    assert profile.weight is None
    assert profile.height is None
    assert profile.health_notes is None
    assert profile.workout_experience is None
    assert profile.workout_goals is None
    assert profile.workout_location is None
    assert cleanup_calls == [(7, "profile_deleted")]
