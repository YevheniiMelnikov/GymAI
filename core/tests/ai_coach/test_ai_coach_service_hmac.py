import httpx
import pytest

from core.exceptions import UserServiceError
from core.services.internal.ai_coach_service import AiCoachService


class DummySettings:
    AI_COACH_URL = "http://test/"
    AI_COACH_TIMEOUT = 1
    AI_COACH_INTERNAL_KEY_ID = ""
    AI_COACH_INTERNAL_API_KEY = ""
    INTERNAL_KEY_ID = ""
    INTERNAL_API_KEY = ""
    ENVIRONMENT = "development"


@pytest.mark.asyncio
async def test_hmac_headers_dev_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_request(*args, **kwargs):
        return 200, {}

    monkeypatch.setattr(AiCoachService, "_api_request", fake_request)
    async with httpx.AsyncClient() as client:
        service = AiCoachService(client, DummySettings())
        assert service._hmac_headers(b"{}") == {}


@pytest.mark.asyncio
async def test_hmac_headers_prod_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = DummySettings()
    settings.ENVIRONMENT = "production"
    async with httpx.AsyncClient() as client:
        service = AiCoachService(client, settings)
        with pytest.raises(UserServiceError):
            service._hmac_headers(b"{}")
