import json
from json import JSONDecodeError
from typing import Any
from loguru import logger
from pydantic import ValidationError

from .base import BaseCacheManager
from core.exceptions import ProfileNotFoundError
from core.schemas import Profile
from core.services import APIService


class ProfileCacheManager(BaseCacheManager):
    @classmethod
    async def _fetch_from_service(cls, cache_key: str, field: str, *, use_fallback: bool) -> Profile:
        profile = await APIService.profile.get_profile_by_tg_id(int(field))
        if profile is None:
            raise ProfileNotFoundError(int(field))
        return profile

    @classmethod
    def _validate_data(cls, raw: str, cache_key: str, field: str) -> Profile:
        try:
            data = json.loads(raw)
            profile = Profile.model_validate(data)
            return profile
        except (JSONDecodeError, TypeError, ValueError, ValidationError) as e:
            logger.debug(f"Corrupt profile in cache for tg={field}: {e}")
            raise ProfileNotFoundError(int(field))

    @classmethod
    async def get_profile(cls, tg_id: int, *, use_fallback: bool = True) -> Profile:
        return await cls.get_or_fetch("profiles", str(tg_id), use_fallback=use_fallback)

    @classmethod
    async def save_profile(cls, tg_id: int, profile_data: dict) -> None:
        try:
            data = dict(profile_data)
            data["tg_id"] = tg_id
            await cls.set("profiles", str(tg_id), json.dumps(data))
            logger.debug(f"Profile saved for tg_id={tg_id}")
        except Exception as e:
            logger.error(f"Failed to save profile for tg_id={tg_id}: {e}")

    @classmethod
    async def update_profile(cls, tg_id: int, updates: dict) -> None:
        try:
            current = await cls.get_json("profiles", str(tg_id)) or {}
            current.update(updates)
            await cls.set_json("profiles", str(tg_id), current)
            logger.debug(f"Profile updated for tg_id={tg_id} with {updates}")
        except Exception as e:
            logger.error(f"Failed to update profile for tg_id={tg_id}: {e}")

    @classmethod
    async def delete_profile(cls, tg_id: int) -> bool:
        try:
            await cls.delete("profiles", str(tg_id))
            logger.info(f"Profile for tg_id {tg_id} has been deleted")
            return True
        except Exception as e:
            logger.error(f"Error deleting profile for tg_id {tg_id}: {e}")
            return False

    @classmethod
    async def save_record(cls, profile_id: int, profile_data: dict[str, Any]) -> None:
        try:
            data = dict(profile_data)
            data["profile"] = profile_id
            data["id"] = profile_id
            await cls.set_json("clients", str(profile_id), data)
            logger.debug(f"Profile record saved for profile_id={profile_id}")
        except Exception as e:
            logger.error(f"Failed to save profile record for profile_id={profile_id}: {e}")

    @classmethod
    async def update_record(cls, profile_id: int, updates: dict[str, Any]) -> None:
        try:
            await cls.update_json("clients", str(profile_id), updates)
            logger.debug(f"Profile record updated for profile_id={profile_id} with {updates}")
        except Exception as e:
            logger.error(f"Failed to update profile record for profile_id={profile_id}: {e}")

    @classmethod
    async def get_record(cls, profile_id: int, *, use_fallback: bool = True) -> Profile:
        raw = await cls.get("clients", str(profile_id))
        if raw:
            try:
                data = json.loads(raw)
                return Profile.model_validate(data)
            except (JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
                logger.debug(f"Corrupt profile record for profile_id={profile_id}: {exc}")
                await cls.delete("clients", str(profile_id))
        if not use_fallback:
            raise ProfileNotFoundError(profile_id)
        profile = await APIService.profile.get_profile(profile_id)
        if profile is None:
            raise ProfileNotFoundError(profile_id)
        await cls.save_record(profile_id, profile.model_dump())
        return profile

    @classmethod
    async def get_all_records(cls) -> dict[str, str]:
        return await cls.get_all("clients")
