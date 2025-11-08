from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable

import pytest
from rest_framework import serializers as rf_serializers
from rest_framework.exceptions import NotFound, ValidationError

if not hasattr(rf_serializers, "DecimalField"):

    class _DecimalFieldStub:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    rf_serializers.DecimalField = _DecimalFieldStub  # type: ignore[attr-defined]

from apps.profiles.repos import (
    ClientProfileRepository,
    CoachProfileRepository,
    ProfileRepository,
)


class ProfileStub:
    """Minimal stand-in for Profile model used by repository tests."""

    DoesNotExist = type("DoesNotExist", (Exception,), {})

    def __init__(self, **data: Any) -> None:
        self.id: int | None = data.get("id")
        self.role: str | None = data.get("role")
        self.tg_id: int | None = data.get("tg_id")
        self.language: str | None = data.get("language")
        self.pk: int | None = data.get("pk")
        self._state: SimpleNamespace = SimpleNamespace(adding=True)
        for name, value in data.items():
            setattr(self, name, value)


class ProfileManagerStub:
    def __init__(self, mapping: dict[str, ProfileStub]) -> None:
        self._mapping: dict[str, ProfileStub] = mapping

    def get(self, **kwargs: Any) -> ProfileStub:
        key: str
        if "pk" in kwargs:
            key = f"pk:{kwargs['pk']}"
        elif "tg_id" in kwargs:
            key = f"tg:{kwargs['tg_id']}"
        else:
            raise AssertionError("Unexpected lookup arguments")

        try:
            return self._mapping[key]
        except KeyError as exc:  # pragma: no cover - exercised via DoesNotExist
            raise ProfileStub.DoesNotExist from exc


class CoachProfileStub:
    DoesNotExist = type("DoesNotExist", (Exception,), {})

    def __init__(self, profile: ProfileStub, **data: Any) -> None:
        self.profile: ProfileStub = profile
        self.pk: int | None = data.get("pk")
        for name, value in data.items():
            setattr(self, name, value)


class CoachProfileManagerStub:
    def __init__(self, instance: CoachProfileStub | None = None) -> None:
        self._instance: CoachProfileStub | None = instance

    def get(self, pk: int) -> CoachProfileStub:
        if self._instance is None:
            raise CoachProfileStub.DoesNotExist
        return self._instance

    def get_or_create(self, profile: ProfileStub) -> tuple[CoachProfileStub, bool]:
        if self._instance is None:
            self._instance = CoachProfileStub(profile=profile)
            return self._instance, True
        return self._instance, False


class ClientProfileStub:
    DoesNotExist = type("DoesNotExist", (Exception,), {})

    def __init__(self, profile: ProfileStub, **data: Any) -> None:
        self.profile: ProfileStub = profile
        self.pk: int | None = data.get("pk")
        for name, value in data.items():
            setattr(self, name, value)


@dataclass(slots=True)
class ClientProfileManagerStub:
    by_pk: dict[int, ClientProfileStub]
    by_profile_id: dict[int, ClientProfileStub]

    def get(self, **kwargs: Any) -> ClientProfileStub:
        if "pk" in kwargs:
            pk: int = kwargs["pk"]
            try:
                return self.by_pk[pk]
            except KeyError as exc:  # pragma: no cover - exercised via DoesNotExist
                raise ClientProfileStub.DoesNotExist from exc
        if "profile_id" in kwargs:
            profile_id: int = kwargs["profile_id"]
            try:
                return self.by_profile_id[profile_id]
            except KeyError as exc:  # pragma: no cover - exercised via DoesNotExist
                raise ClientProfileStub.DoesNotExist from exc
        raise AssertionError("Unexpected lookup arguments")

    def get_or_create(self, profile: ProfileStub) -> tuple[ClientProfileStub, bool]:
        existing: ClientProfileStub | None = self.by_profile_id.get(profile.id or -1)
        if existing is not None:
            return existing, False
        created: ClientProfileStub = ClientProfileStub(profile=profile)
        if profile.id is not None:
            self.by_profile_id[profile.id] = created
        return created, True


class ProfileSerializerStub:
    def __init__(self, instance: ProfileStub) -> None:
        self.data: dict[str, Any] = {
            "id": instance.id,
            "role": instance.role,
            "tg_id": instance.tg_id,
            "language": instance.language,
        }


def test_get_model_by_id_returns_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    profile: ProfileStub = ProfileStub(id=7, role="client")
    manager: ProfileManagerStub = ProfileManagerStub({"pk:7": profile})
    monkeypatch.setattr(ProfileStub, "objects", manager, raising=False)
    monkeypatch.setattr("apps.profiles.repos.Profile", ProfileStub)
    monkeypatch.setattr("apps.profiles.repos.settings", SimpleNamespace(CACHE_TTL=60), raising=False)

    result: ProfileStub = ProfileRepository.get_model_by_id(7)

    assert result is profile


def test_get_model_by_id_raises_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    manager: ProfileManagerStub = ProfileManagerStub({})
    monkeypatch.setattr(ProfileStub, "objects", manager, raising=False)
    monkeypatch.setattr("apps.profiles.repos.Profile", ProfileStub)
    monkeypatch.setattr("apps.profiles.repos.settings", SimpleNamespace(CACHE_TTL=60), raising=False)

    with pytest.raises(NotFound):
        ProfileRepository.get_model_by_id(42)


def test_get_by_id_reconstructs_profile_from_cached_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apps.profiles.repos.Profile", ProfileStub)
    monkeypatch.setattr("apps.profiles.repos.settings", SimpleNamespace(CACHE_TTL=60), raising=False)

    def fake_get_or_set(key: str, fetch: Callable[[], dict[str, Any]], timeout: int) -> dict[str, Any]:
        assert key == "profile:7"
        return {
            "id": 7,
            "role": "client",
            "language": "en",
            "tg_id": 99,
        }

    monkeypatch.setattr("apps.profiles.repos.cache.get_or_set", fake_get_or_set)

    profile: ProfileStub = ProfileRepository.get_by_id(7)

    assert isinstance(profile, ProfileStub)
    assert profile.pk == 7
    assert profile._state.adding is False


def test_get_by_id_returns_cached_model_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    profile: ProfileStub = ProfileStub(id=5, role="client")
    manager: ProfileManagerStub = ProfileManagerStub({"pk:5": profile})
    monkeypatch.setattr(ProfileStub, "objects", manager, raising=False)
    monkeypatch.setattr("apps.profiles.repos.Profile", ProfileStub)
    monkeypatch.setattr("apps.profiles.repos.settings", SimpleNamespace(CACHE_TTL=60), raising=False)

    monkeypatch.setattr("apps.profiles.repos.ProfileSerializer", ProfileSerializerStub)

    def fake_get_or_set(key: str, fetch: Callable[[], Any], timeout: int) -> ProfileStub:
        assert key == "profile:5"
        return profile

    monkeypatch.setattr("apps.profiles.repos.cache.get_or_set", fake_get_or_set)

    result: ProfileStub = ProfileRepository.get_by_id(5)

    assert result is profile


def test_get_by_telegram_id_reconstructs_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apps.profiles.repos.Profile", ProfileStub)
    monkeypatch.setattr("apps.profiles.repos.settings", SimpleNamespace(CACHE_TTL=60), raising=False)

    def fake_get_or_set(key: str, fetch: Callable[[], dict[str, Any]], timeout: int) -> dict[str, Any]:
        assert key == "profile:tg:500"
        return {
            "id": 11,
            "role": "client",
            "language": "uk",
            "tg_id": 500,
        }

    monkeypatch.setattr("apps.profiles.repos.cache.get_or_set", fake_get_or_set)

    profile: ProfileStub = ProfileRepository.get_by_telegram_id(500)

    assert isinstance(profile, ProfileStub)
    assert profile.tg_id == 500
    assert profile._state.adding is False


def test_get_by_telegram_id_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    manager: ProfileManagerStub = ProfileManagerStub({})
    monkeypatch.setattr(ProfileStub, "objects", manager, raising=False)
    monkeypatch.setattr("apps.profiles.repos.Profile", ProfileStub)
    monkeypatch.setattr("apps.profiles.repos.settings", SimpleNamespace(CACHE_TTL=60), raising=False)
    monkeypatch.setattr("apps.profiles.repos.ProfileSerializer", ProfileSerializerStub)

    def fake_get_or_set(key: str, fetch: Callable[[], dict[str, Any]], timeout: int) -> dict[str, Any]:
        assert key == "profile:tg:404"
        return fetch()

    monkeypatch.setattr("apps.profiles.repos.cache.get_or_set", fake_get_or_set)

    with pytest.raises(NotFound):
        ProfileRepository.get_by_telegram_id(404)


def test_coach_profile_get_validates_role(monkeypatch: pytest.MonkeyPatch) -> None:
    coach_profile: CoachProfileStub = CoachProfileStub(profile=ProfileStub(role="client"))
    manager: CoachProfileManagerStub = CoachProfileManagerStub(coach_profile)
    monkeypatch.setattr(CoachProfileStub, "objects", manager, raising=False)
    monkeypatch.setattr("apps.profiles.repos.CoachProfile", CoachProfileStub)

    with pytest.raises(ValidationError):
        CoachProfileRepository.get(1)


def test_coach_profile_get_or_create_requires_coach_role(monkeypatch: pytest.MonkeyPatch) -> None:
    profile: ProfileStub = ProfileStub(role="client")
    manager: CoachProfileManagerStub = CoachProfileManagerStub()
    monkeypatch.setattr(CoachProfileStub, "objects", manager, raising=False)
    monkeypatch.setattr("apps.profiles.repos.CoachProfile", CoachProfileStub)

    with pytest.raises(ValidationError):
        CoachProfileRepository.get_or_create_by_profile(profile)


def test_coach_profile_get_or_create_creates(monkeypatch: pytest.MonkeyPatch) -> None:
    profile: ProfileStub = ProfileStub(role="coach", id=3)
    manager: CoachProfileManagerStub = CoachProfileManagerStub()
    monkeypatch.setattr(CoachProfileStub, "objects", manager, raising=False)
    monkeypatch.setattr("apps.profiles.repos.CoachProfile", CoachProfileStub)

    created: CoachProfileStub = CoachProfileRepository.get_or_create_by_profile(profile)

    assert isinstance(created, CoachProfileStub)
    assert created.profile is profile


def test_client_profile_get_validates_role(monkeypatch: pytest.MonkeyPatch) -> None:
    client_profile: ClientProfileStub = ClientProfileStub(profile=ProfileStub(role="coach"), pk=1)
    manager: ClientProfileManagerStub = ClientProfileManagerStub({1: client_profile}, {})
    monkeypatch.setattr(ClientProfileStub, "objects", manager, raising=False)
    monkeypatch.setattr("apps.profiles.repos.ClientProfile", ClientProfileStub)

    with pytest.raises(ValidationError):
        ClientProfileRepository.get(1)


def test_client_profile_get_by_profile_id(monkeypatch: pytest.MonkeyPatch) -> None:
    profile: ProfileStub = ProfileStub(role="client", id=5)
    client_profile: ClientProfileStub = ClientProfileStub(profile=profile, pk=7)
    manager: ClientProfileManagerStub = ClientProfileManagerStub({7: client_profile}, {5: client_profile})
    monkeypatch.setattr(ClientProfileStub, "objects", manager, raising=False)
    monkeypatch.setattr("apps.profiles.repos.ClientProfile", ClientProfileStub)

    result: ClientProfileStub = ClientProfileRepository.get_by_profile_id(5)

    assert result is client_profile


def test_client_profile_get_or_create_requires_client_role(monkeypatch: pytest.MonkeyPatch) -> None:
    profile: ProfileStub = ProfileStub(role="coach", id=2)
    manager: ClientProfileManagerStub = ClientProfileManagerStub({}, {})
    monkeypatch.setattr(ClientProfileStub, "objects", manager, raising=False)
    monkeypatch.setattr("apps.profiles.repos.ClientProfile", ClientProfileStub)

    with pytest.raises(ValidationError):
        ClientProfileRepository.get_or_create_by_profile(profile)


def test_client_profile_get_or_create_returns_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    profile: ProfileStub = ProfileStub(role="client", id=10)
    existing: ClientProfileStub = ClientProfileStub(profile=profile, pk=11)
    manager: ClientProfileManagerStub = ClientProfileManagerStub({11: existing}, {10: existing})
    monkeypatch.setattr(ClientProfileStub, "objects", manager, raising=False)
    monkeypatch.setattr("apps.profiles.repos.ClientProfile", ClientProfileStub)

    result: ClientProfileStub = ClientProfileRepository.get_or_create_by_profile(profile)

    assert result is existing
