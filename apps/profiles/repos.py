from typing import cast
from django.core.cache import cache
from rest_framework.exceptions import NotFound

from apps.profiles.models import Profile
from apps.profiles.serializers import ProfileSerializer
from config.app_settings import settings


class ProfileRepository:
    """Provide cached access helpers for profile records."""

    @staticmethod
    def get_model_by_id(profile_id: int) -> Profile:
        try:
            return Profile.objects.get(pk=profile_id)  # pyrefly: ignore[missing-attribute]
        except Profile.DoesNotExist:  # pyrefly: ignore[missing-attribute]
            raise NotFound(f"Profile pk={profile_id} not found")

    @staticmethod
    def get_by_id(profile_id: int) -> Profile:
        cache_key = f"profile:{profile_id}"
        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            exists = Profile.objects.filter(pk=profile_id).only("id").exists()  # pyrefly: ignore[missing-attribute]
            if not exists:
                cache.delete(cache_key)
                raise NotFound(f"Profile pk={profile_id} not found")
        else:
            instance = ProfileRepository.get_model_by_id(profile_id)
            cached = ProfileSerializer(instance).data
            cache.set(cache_key, cached, settings.CACHE_TTL)

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
        cache_key = f"profile:tg:{tg_id}"
        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            exists = Profile.objects.filter(tg_id=tg_id).only("id").exists()  # pyrefly: ignore[missing-attribute]
            if not exists:
                cache.delete(cache_key)
                raise NotFound(f"Profile with tg_id={tg_id} not found")
        else:
            try:
                instance = Profile.objects.get(tg_id=tg_id)  # pyrefly: ignore[missing-attribute]
            except Profile.DoesNotExist:  # pyrefly: ignore[missing-attribute]
                raise NotFound(f"Profile with tg_id={tg_id} not found")
            cached = ProfileSerializer(instance).data
            cache.set(cache_key, cached, settings.CACHE_TTL)

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
