from types import SimpleNamespace

import pytest

from core.services.internal.profile_service import ProfileService


class DummyProfileRepository:
    def __init__(self, delete_result: bool) -> None:
        self.delete_result = delete_result
        self.deleted_ids: list[int] = []

    async def delete_profile(self, profile_id: int) -> bool:
        self.deleted_ids.append(profile_id)
        return self.delete_result

    async def get_profile(self, profile_id: int):
        raise NotImplementedError

    async def get_profile_by_tg_id(self, tg_id: int):
        raise NotImplementedError

    async def create_profile(self, tg_id: int, language: str):
        raise NotImplementedError

    async def update_profile(self, profile_id: int, data: dict):
        raise NotImplementedError

    async def adjust_credits(self, profile_id: int, delta):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_delete_profile_enqueues_cleanup(monkeypatch):
    task_calls: list[int] = []

    monkeypatch.setattr(
        "core.services.internal.profile_service.cleanup_profile_knowledge",
        SimpleNamespace(delay=lambda profile_id: task_calls.append(profile_id)),
    )

    service = ProfileService(DummyProfileRepository(delete_result=True))
    assert await service.delete_profile(42) is True
    assert task_calls == [42]


@pytest.mark.asyncio
async def test_delete_profile_skip_cleanup_when_failed(monkeypatch):
    task_calls: list[int] = []

    monkeypatch.setattr(
        "core.services.internal.profile_service.cleanup_profile_knowledge",
        SimpleNamespace(delay=lambda profile_id: task_calls.append(profile_id)),
    )

    service = ProfileService(DummyProfileRepository(delete_result=False))
    assert await service.delete_profile(99) is False
    assert task_calls == []
