import asyncio
import httpx
import pytest

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
            payload: dict[str, object],
            headers: dict[str, str] | None = None,
            timeout: float | None = None,
        ) -> tuple[int, dict[str, object]]:
            self.sent_headers = headers
            return 200, {}

        async with httpx.AsyncClient() as client:
            service = AiCoachService(client, DummySettings())
            monkeypatch.setattr(AiCoachService, "_api_request", fake_api_request)
            await service.ask("hi", client_id=1, use_agent_header=True)
            assert service.sent_headers["X-Agent"] == "pydanticai"

    asyncio.run(runner())
