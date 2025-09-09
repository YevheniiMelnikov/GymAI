from decimal import Decimal
from typing import Any

from core.domain.profile_repository import ProfileRepository
from core.schemas import Coach, Client, Profile


class ProfileService:
    def __init__(self, repository: ProfileRepository) -> None:
        self._repository = repository

    async def get_profile(self, profile_id: int) -> Profile | None:
        return await self._repository.get_profile(profile_id)

    async def get_profile_by_tg_id(self, tg_id: int) -> Profile | None:
        return await self._repository.get_profile_by_tg_id(tg_id)

    async def create_profile(self, tg_id: int, role: str, language: str) -> Profile | None:
        return await self._repository.create_profile(tg_id, role, language)

    async def delete_profile(self, profile_id: int, token: str | None = None) -> bool:
        return await self._repository.delete_profile(profile_id, token)

    async def update_profile(self, profile_id: int, data: dict[str, Any]) -> bool:
        return await self._repository.update_profile(profile_id, data)

    async def create_client_profile(self, profile_id: int, data: dict[str, Any] | None = None) -> Client | None:
        return await self._repository.create_client_profile(profile_id, data)

    async def update_client_profile(self, client_profile_id: int, data: dict[str, Any]) -> bool:
        return await self._repository.update_client_profile(client_profile_id, data)

    async def adjust_client_credits(self, profile_id: int, delta: int | Decimal) -> bool:
        return await self._repository.adjust_client_credits(profile_id, delta)

    async def adjust_coach_payout_due(self, profile_id: int, delta: Decimal) -> bool:
        return await self._repository.adjust_coach_payout_due(profile_id, delta)

    async def create_coach_profile(self, profile_id: int, data: dict[str, Any] | None = None) -> Coach | None:
        return await self._repository.create_coach_profile(profile_id, data)

    async def update_coach_profile(self, coach_id: int, data: dict[str, Any]) -> bool:
        return await self._repository.update_coach_profile(coach_id, data)

    async def get_client_by_profile_id(self, profile_id: int) -> Client | None:
        return await self._repository.get_client_by_profile_id(profile_id)

    async def get_coach_by_profile_id(self, profile_id: int) -> Coach | None:
        return await self._repository.get_coach_by_profile_id(profile_id)

    async def get_client_by_tg_id(self, tg_id: int) -> Client | None:
        return await self._repository.get_client_by_tg_id(tg_id)

    async def get_coach_by_tg_id(self, tg_id: int) -> Coach | None:
        return await self._repository.get_coach_by_tg_id(tg_id)

    async def list_coach_profiles(self) -> list[Coach]:
        return await self._repository.list_coach_profiles()
