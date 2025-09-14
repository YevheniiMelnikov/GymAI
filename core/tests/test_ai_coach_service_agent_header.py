import pytest
import httpx

from core.services.internal.ai_coach_service import AiCoachService


class DummySettings:
    AI_COACH_URL = "http://test/"
    AI_COACH_TIMEOUT = 1


@pytest.mark.asyncio
async def test_agent_header(monkeypatch):
    async def fake_api_request(self, method, url, payload, headers=None, timeout=None):
        self.sent_headers = headers
        return 200, {}

    client = httpx.AsyncClient()
    service = AiCoachService(client, DummySettings())
    monkeypatch.setattr(AiCoachService, "_api_request", fake_api_request)
    await service.ask("hi", client_id=1, use_agent_header=True)
    assert service.sent_headers["X-Agent"] == "pydanticai"
    await client.aclose()
