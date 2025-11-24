import asyncio
import pytest
from core.cache.workout import WorkoutCacheManager
from core.exceptions import UserServiceError


def test_get_latest_program_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def fake_get_or_fetch(*args, **kwargs):
            raise UserServiceError("down")

        async def fake_get_json(key: str, field: str):
            assert key == "workout_plans:programs_history"
            return [
                {
                    "id": 1,
                    "profile": int(field),
                    "exercises_by_day": [],
                    "created_at": 5,
                }
            ]

        monkeypatch.setattr(WorkoutCacheManager, "get_or_fetch", fake_get_or_fetch)
        monkeypatch.setattr(WorkoutCacheManager, "get_json", fake_get_json)
        monkeypatch.setattr(WorkoutCacheManager, "delete", lambda *a, **k: None)

        program = await WorkoutCacheManager.get_latest_program(1)
        assert program.id == 1
        assert program.created_at == 5

    asyncio.run(runner())
