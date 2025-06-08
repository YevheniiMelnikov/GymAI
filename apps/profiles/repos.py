from __future__ import annotations

from typing import cast
from django.core.cache import cache
from rest_framework.exceptions import ValidationError, NotFound

from apps.profiles.models import Profile, CoachProfile, ClientProfile
from config.env_settings import settings


class ProfileRepository:
    @staticmethod
    def get_by_id(profile_id: int) -> Profile:
        def get_profile() -> Profile:
            try:
                profile = Profile.objects.get(pk=profile_id)
                return cast(Profile, profile)
            except Profile.DoesNotExist:
                raise NotFound(f"Profile pk={profile_id} not found")

        result = cache.get_or_set(
            f"profile:{profile_id}",
            get_profile,
            settings.CACHE_TTL,
        )
        return cast(Profile, result)

    @staticmethod
    def get_by_telegram_id(tg_id: int) -> Profile:
        def get_profile() -> Profile:
            try:
                profile = Profile.objects.get(tg_id=tg_id)
                return cast(Profile, profile)
            except Profile.DoesNotExist:
                raise NotFound(f"Profile with tg_id={tg_id} not found")

        result = cache.get_or_set(
            f"profile:tg:{tg_id}",
            get_profile,
            settings.CACHE_TTL,
        )
        return cast(Profile, result)


class CoachProfileRepository:
    @staticmethod
    def get(pk: int) -> CoachProfile:
        try:
            coach_profile = CoachProfile.objects.get(pk=pk)
            coach_profile = cast(CoachProfile, coach_profile)
        except CoachProfile.DoesNotExist:
            raise NotFound(f"CoachProfile pk={pk} not found")
        if coach_profile.profile.status != "coach":  # type: ignore[attr-defined]
            raise ValidationError("Underlying profile status is not 'coach'")
        return coach_profile

    @staticmethod
    def get_or_create_by_profile(profile: Profile) -> CoachProfile:
        if profile.status != "coach":
            raise ValidationError("Profile status is not 'coach'")
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
        if client_profile.profile.status != "client":  # type: ignore[attr-defined]
            raise ValidationError("Underlying profile status is not 'client'")
        return client_profile

    @staticmethod
    def get_or_create_by_profile(profile: Profile) -> ClientProfile:
        if profile.status != "client":
            raise ValidationError("Profile status is not 'client'")
        client_profile, _ = ClientProfile.objects.get_or_create(profile=profile)
        return cast(ClientProfile, client_profile)
