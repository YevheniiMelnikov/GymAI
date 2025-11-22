import asyncio
import httpx
import pytest

from core.enums import WorkoutPlanType
from core.exceptions import UserServiceError
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
            return 200, {"answer": "ok"}

        async with httpx.AsyncClient() as client:
            service = AiCoachService(client, DummySettings())
            monkeypatch.setattr(AiCoachService, "_api_request", fake_api_request)
            await service.ask("hi", profile_id=1, use_agent_header=True)
            assert service.sent_headers["X-Agent"] == "pydanticai"

    asyncio.run(runner())


@pytest.mark.asyncio
async def test_create_program_invalid_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(
        self,
        payload: object,
        *,
        request_id: str | None,
        extra_headers: dict[str, str] | None = None,
    ) -> list[object]:
        return []

    monkeypatch.setattr(AiCoachService, "_post_ask", fake_post)

    async with httpx.AsyncClient() as client:
        service = AiCoachService(client, DummySettings())
        with pytest.raises(UserServiceError) as exc_info:
            await service.create_workout_plan(
                WorkoutPlanType.PROGRAM,
                profile_id=1,
                language="ua",
                request_id="test",
            )

    assert "invalid program payload" in str(exc_info.value)
