import asyncio
import httpx
import pytest

from core.enums import WorkoutPlanType
from core.schemas import Program
from core.services.internal.ai_coach_service import AiCoachService


class DummySettings:
    AI_COACH_URL = "http://test/"
    AI_COACH_TIMEOUT = 1


def test_agent_header(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def fake_api_request(
            self,
            method: str,
            url: str,
            payload: dict[str, object] | None = None,
            headers: dict[str, str] | None = None,
            timeout: float | None = None,
            *,
            client: httpx.AsyncClient | None = None,
        ) -> tuple[int, dict[str, object]]:
            self.sent_headers = headers
            return 200, {}

        async with httpx.AsyncClient() as client:
            service = AiCoachService(client, DummySettings())
            monkeypatch.setattr(AiCoachService, "_api_request", fake_api_request)
            await service.ask("hi", client_id=1, use_agent_header=True)
            assert service.sent_headers["X-Agent"] == "pydanticai"

    asyncio.run(runner())


@pytest.mark.asyncio
async def test_create_program_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(
        self,
        payload: object,
        *,
        request_id: str | None,
        extra_headers: dict[str, str] | None = None,
    ) -> list[object]:
        return []

    fallback_program = Program.model_validate(
        {
            "id": 7,
            "client_profile": 1,
            "created_at": 0,
            "split_number": 1,
            "workout_type": "gym",
            "exercises_by_day": [{"day": "Пн", "exercises": [{"name": "Squat", "sets": "3", "reps": "10"}]}],
        }
    )

    async def fake_latest_program(client_profile_id: int) -> Program | None:
        assert client_profile_id == 1
        return fallback_program

    import core.services as core_services

    monkeypatch.setattr(AiCoachService, "_post_ask", fake_post)
    monkeypatch.setattr(core_services.APIService.workout, "get_latest_program", fake_latest_program)

    async with httpx.AsyncClient() as client:
        service = AiCoachService(client, DummySettings())
        result = await service.create_workout_plan(
            WorkoutPlanType.PROGRAM,
            client_id=1,
            language="ua",
            request_id="test",
        )

    assert isinstance(result, Program)
    assert result.id == fallback_program.id
