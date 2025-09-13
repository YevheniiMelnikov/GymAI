import asyncio

from core.services.internal.ai_coach_service import AiCoachService


class DummySettings:
    AI_COACH_URL = "http://test/"
    AI_COACH_TIMEOUT = 1
    API_URL = "http://localhost/"
    API_KEY = "k"
    API_MAX_RETRIES = 1
    API_RETRY_INITIAL_DELAY = 0
    API_RETRY_BACKOFF_FACTOR = 1
    API_RETRY_MAX_DELAY = 0
    API_TIMEOUT = 1
    AI_COACH_REFRESH_USER = "u"
    AI_COACH_REFRESH_PASSWORD = "p"


def test_agent_header(monkeypatch):
    async def fake_api_request(self, method, url, payload, headers=None, timeout=None):
        self.sent_headers = headers
        return 200, {}

    service = AiCoachService(object(), DummySettings())
    monkeypatch.setattr(AiCoachService, "_api_request", fake_api_request)
    asyncio.run(service.ask("hi", client_id=1, use_agent_header=True))
    assert service.sent_headers["X-Agent"] == "pydanticai"
