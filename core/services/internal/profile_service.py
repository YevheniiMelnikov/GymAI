from decimal import Decimal
from typing import Any

from core.domain.profile_repository import ProfileRepository
from core.schemas import Profile


class ProfileService:
    def __init__(self, repository: ProfileRepository) -> None:
        self._repository = repository

    async def get_profile(self, profile_id: int) -> Profile | None:
        return await self._repository.get_profile(profile_id)

    async def get_profile_by_tg_id(self, tg_id: int) -> Profile | None:
        return await self._repository.get_profile_by_tg_id(tg_id)

    async def create_profile(self, tg_id: int, language: str) -> Profile | None:
        return await self._repository.create_profile(tg_id, language)

    async def delete_profile(self, profile_id: int) -> bool:
        deleted = await self._repository.delete_profile(profile_id)
        if deleted:
            from core.tasks.ai_coach.maintenance import cleanup_profile_knowledge

            getattr(cleanup_profile_knowledge, "delay")(profile_id)
        return deleted

    async def update_profile(self, profile_id: int, data: dict[str, Any]) -> bool:
        return await self._repository.update_profile(profile_id, data)

    async def adjust_credits(self, profile_id: int, delta: int | Decimal) -> bool:
        return await self._repository.adjust_credits(profile_id, delta)
