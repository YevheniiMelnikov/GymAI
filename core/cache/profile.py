from typing import Any

from loguru import logger
from pydantic import ValidationError

from .base import BaseCacheManager
from core.exceptions import ProfileNotFoundError
from core.schemas import Profile
from core.services import APIService


class ProfileCacheManager(BaseCacheManager):
    PROFILE_DATA_KEY = "profiles"

    @classmethod
    async def _cache_profile_data(cls, profile_id: int, profile_data: dict[str, Any]) -> None:
        data = dict(profile_data)
        data["id"] = profile_id
        tg_id = data.get("tg_id")
        if tg_id is None:
            logger.error(f"Cannot cache profile {profile_id}: missing tg_id")
            return
        try:
            int(tg_id)
        except (TypeError, ValueError):
            logger.error(f"Cannot cache profile {profile_id}: invalid tg_id={tg_id}")
            return
        await cls.set_json(cls.PROFILE_DATA_KEY, str(profile_id), data)

    @classmethod
    async def _fetch_profile_by_tg(cls, tg_id: int) -> Profile:
        profile = await APIService.profile.get_profile_by_tg_id(int(tg_id))
        if profile is None:
            raise ProfileNotFoundError(int(tg_id))
        await cls._cache_profile_data(profile.id, profile.model_dump(mode="json"))
        return profile

    @classmethod
    async def _fetch_profile_by_id(cls, profile_id: int) -> Profile:
        profile = await APIService.profile.get_profile(profile_id)
        if profile is None:
            raise ProfileNotFoundError(profile_id)
        await cls._cache_profile_data(profile.id, profile.model_dump(mode="json"))
        return profile

    @classmethod
    async def _migrate_legacy_profile(cls, tg_id: int) -> Profile | None:
        legacy = await cls.get_json(cls.PROFILE_DATA_KEY, str(tg_id))
        if not legacy:
            return None
        try:
            profile = Profile.model_validate(legacy)
        except (ValidationError, TypeError, ValueError) as exc:
            logger.debug(f"Corrupt legacy profile cache tg_id={tg_id}: {exc}")
            await cls.delete(cls.PROFILE_DATA_KEY, str(tg_id))
            return None
        await cls._cache_profile_data(profile.id, profile.model_dump(mode="json"))
        await cls.delete(cls.PROFILE_DATA_KEY, str(tg_id))
        return profile

    @classmethod
    async def get_profile(cls, tg_id: int, *, use_fallback: bool = True) -> Profile:
        migrated = await cls._migrate_legacy_profile(tg_id)
        if migrated:
            return migrated
        if not use_fallback:
            raise ProfileNotFoundError(int(tg_id))
        return await cls._fetch_profile_by_tg(tg_id)

    @classmethod
    async def save_profile(cls, tg_id: int, profile_data: dict) -> None:
        profile_id = profile_data.get("id") or profile_data.get("profile")
        if profile_id is None:
            logger.error("Profile data missing id, cannot save to cache")
            return
        await cls._cache_profile_data(int(profile_id), profile_data)

    @classmethod
    async def update_profile(cls, tg_id: int, updates: dict) -> None:
        try:
            profile = await cls._fetch_profile_by_tg(tg_id)
        except ProfileNotFoundError:
            logger.warning(f"Cannot update profile cache - profile not found for tg_id={tg_id}")
            return
        await cls.update_record(profile.id, updates)

    @classmethod
    async def delete_profile(cls, tg_id: int) -> bool:
        try:
            profile = await APIService.profile.get_profile_by_tg_id(int(tg_id))
            if profile is None:
                logger.warning(f"Profile not found when deleting cache for tg_id={tg_id}")
                return False
            await cls.delete(cls.PROFILE_DATA_KEY, str(profile.id))
            logger.info(f"Profile cache cleared for tg_id={tg_id}")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Failed to delete profile cache for tg_id={tg_id}: {exc}")
            return False

    @classmethod
    async def delete_record(cls, profile_id: int) -> None:
        await cls.delete(cls.PROFILE_DATA_KEY, str(profile_id))
        logger.info(f"Profile cache cleared for profile_id={profile_id}")

    @classmethod
    async def update_record(cls, profile_id: int, updates: dict[str, Any]) -> None:
        try:
            await cls.update_json(cls.PROFILE_DATA_KEY, str(profile_id), updates)
            logger.debug(f"Profile record updated profile_id={profile_id} with {updates}")
        except Exception as exc:
            logger.error(f"Failed to update profile record profile_id={profile_id}: {exc}")

    @classmethod
    async def save_record(cls, profile_id: int, profile_data: dict[str, Any]) -> None:
        try:
            await cls._cache_profile_data(profile_id, profile_data)
            logger.debug(f"Profile record saved profile_id={profile_id}")
        except Exception as exc:
            logger.error(f"Failed to save profile record profile_id={profile_id}: {exc}")

    @classmethod
    async def get_record(cls, profile_id: int, *, use_fallback: bool = True) -> Profile:
        raw = await cls.get_json(cls.PROFILE_DATA_KEY, str(profile_id))
        if raw:
            try:
                profile = Profile.model_validate(raw)
                return profile
            except (ValidationError, TypeError, ValueError) as exc:
                logger.debug(f"Corrupt profile record for profile_id={profile_id}: {exc}")
                await cls.delete(cls.PROFILE_DATA_KEY, str(profile_id))
        if not use_fallback:
            raise ProfileNotFoundError(profile_id)
        return await cls._fetch_profile_by_id(profile_id)

    @classmethod
    async def get_all_records(cls) -> dict[str, str]:
        return await cls.get_all(cls.PROFILE_DATA_KEY)
