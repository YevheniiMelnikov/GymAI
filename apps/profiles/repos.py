from typing import cast, Dict, Any
from django.core.cache import cache
from rest_framework.exceptions import NotFound

from apps.profiles.models import Profile
from apps.profiles.serializers import ProfileSerializer
from config.app_settings import settings


class ProfileRepository:
    @staticmethod
    def get_model_by_id(profile_id: int) -> Profile:
        try:
            return Profile.objects.get(pk=profile_id)  # pyrefly: ignore[missing-attribute]
        except Profile.DoesNotExist:  # pyrefly: ignore[missing-attribute]
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
            pk_value = cached.get("id")
            if pk_value is not None:
                profile.pk = int(pk_value)
            profile._state.adding = False
            return profile

        return cast(Profile, cached)

    @staticmethod
    def get_by_profile_id(profile_id: int) -> Profile:
        return ProfileRepository.get_by_id(profile_id)

    @staticmethod
    def get_by_telegram_id(tg_id: int) -> Profile:
        def fetch_profile() -> Dict[str, Any]:
            try:
                instance = Profile.objects.get(tg_id=tg_id)  # pyrefly: ignore[missing-attribute]
            except Profile.DoesNotExist:  # pyrefly: ignore[missing-attribute]
                raise NotFound(f"Profile with tg_id={tg_id} not found")
            return ProfileSerializer(instance).data

        cached = cache.get_or_set(
            f"profile:tg:{tg_id}",
            fetch_profile,
            settings.CACHE_TTL,
        )

        if isinstance(cached, dict):
            profile = Profile(**cached)
            pk_value = cached.get("id")
            if pk_value is not None:
                profile.pk = int(pk_value)
            profile._state.adding = False
            return profile

        return cast(Profile, cached)

    @staticmethod
    def invalidate_cache(profile_id: int, tg_id: int | None) -> None:
        cache.delete(f"profile:{profile_id}")
        if tg_id is not None:
            cache.delete(f"profile:tg:{tg_id}")
