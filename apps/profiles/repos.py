from __future__ import annotations

from typing import cast, Dict, Any
from django.core.cache import cache
from rest_framework.exceptions import ValidationError, NotFound

from apps.profiles.models import Profile, CoachProfile, ClientProfile
from apps.profiles.serializers import ProfileSerializer
from config.env_settings import settings


class ProfileRepository:
    @staticmethod
    def get_model_by_id(profile_id: int) -> Profile:
        try:
            profile = Profile.objects.get(pk=profile_id)
            return cast(Profile, profile)
        except Profile.DoesNotExist:
            raise NotFound(f"Profile pk={profile_id} not found")

    @staticmethod
    def get_by_id(profile_id: int) -> Profile:
        def fetch_profile() -> Dict[str, Any]:
            instance = ProfileRepository.get_model_by_id(profile_id)
            return ProfileSerializer(instance).data

        cached = cache.get_or_set(
            f"profile:{profile_id}",
            fetch_profile,
            settings.CACHE_TTL,
        )

        if isinstance(cached, dict):
            profile = Profile(**cached)
            profile.pk = cached.get("id")
            profile._state.adding = False
            return profile

        return cast(Profile, cached)

    @staticmethod
    def get_by_telegram_id(tg_id: int) -> Profile:
        def fetch_profile() -> Dict[str, Any]:
            try:
                instance = Profile.objects.get(tg_id=tg_id)
                instance = cast(Profile, instance)
            except Profile.DoesNotExist:
                raise NotFound(f"Profile with tg_id={tg_id} not found")
            return ProfileSerializer(instance).data

        cached = cache.get_or_set(
            f"profile:tg:{tg_id}",
            fetch_profile,
            settings.CACHE_TTL,
        )

        if isinstance(cached, dict):
            profile = Profile(**cached)
            profile.pk = cached.get("id")
            profile._state.adding = False
            return profile

        return cast(Profile, cached)


class CoachProfileRepository:
    @staticmethod
    def get(pk: int) -> CoachProfile:
        try:
            coach_profile = CoachProfile.objects.get(pk=pk)
            coach_profile = cast(CoachProfile, coach_profile)
        except CoachProfile.DoesNotExist:
            raise NotFound(f"CoachProfile pk={pk} not found")
        if coach_profile.profile.role != "coach":  # type: ignore[attr-defined]
            raise ValidationError("Underlying profile role is not 'coach'")
        return coach_profile

    @staticmethod
    def get_or_create_by_profile(profile: Profile) -> CoachProfile:
        if profile.role != "coach":
            raise ValidationError("Profile role is not 'coach'")
        coach_profile, _ = CoachProfile.objects.get_or_create(profile=profile)
        return cast(CoachProfile, coach_profile)


class ClientProfileRepository:
    @staticmethod
    def get(pk: int) -> ClientProfile:
        try:
            client_profile = ClientProfile.objects.get(pk=pk)
            client_profile = cast(ClientProfile, client_profile)
        except ClientProfile.DoesNotExist:
            raise NotFound(f"ClientProfile pk={pk} not found")
        if client_profile.profile.role != "client":  # type: ignore[attr-defined]
            raise ValidationError("Underlying profile role is not 'client'")
        return client_profile

    @staticmethod
    def get_or_create_by_profile(profile: Profile) -> ClientProfile:
        if profile.role != "client":
            raise ValidationError("Profile role is not 'client'")
        client_profile, _ = ClientProfile.objects.get_or_create(profile=profile)
        return cast(ClientProfile, client_profile)
