import sys
from importlib import import_module
from types import SimpleNamespace

import pytest
from django.http import HttpRequest, JsonResponse

from core.cache import Cache
from core.exceptions import UserServiceError


django_http = sys.modules["django.http"]
django_http.HttpResponse = object  # type: ignore[attr-defined]
django_shortcuts = sys.modules.setdefault("django.shortcuts", SimpleNamespace(render=lambda *a, **k: None))

views = import_module("apps.webapp.views")


@pytest.mark.asyncio
async def test_subscription_data_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def mock_get_profile(tg_id: int, *, use_fallback: bool = True) -> SimpleNamespace:
        return SimpleNamespace(id=1)

    async def mock_get_client(profile_id: int, *, use_fallback: bool = True) -> SimpleNamespace:
        return SimpleNamespace(id=1)

    async def mock_get_subscription(client_id: int, *, use_fallback: bool = True) -> SimpleNamespace:
        return SimpleNamespace(exercises=[])

    monkeypatch.setattr(views, "verify_init_data", lambda _d: {"user": {"id": 1}})
    monkeypatch.setattr(Cache.profile, "get_profile", mock_get_profile)
    monkeypatch.setattr(Cache.client, "get_client", mock_get_client)
    monkeypatch.setattr(Cache.workout, "get_latest_subscription", mock_get_subscription)

    request: HttpRequest = HttpRequest()
    request.method = "GET"
    request.GET = {"init_data": "data"}

    response: JsonResponse = await views.subscription_data(request)
    assert response.status_code == 200
    assert response["program"] == ""


@pytest.mark.asyncio
async def test_subscription_data_service_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def mock_get_profile(tg_id: int, *, use_fallback: bool = True) -> SimpleNamespace:
        return SimpleNamespace(id=1)

    async def mock_get_client(profile_id: int, *, use_fallback: bool = True) -> SimpleNamespace:
        return SimpleNamespace(id=1)

    async def mock_get_subscription(client_id: int, *, use_fallback: bool = True) -> SimpleNamespace:
        raise UserServiceError("down")

    monkeypatch.setattr(views, "verify_init_data", lambda _d: {"user": {"id": 1}})
    monkeypatch.setattr(Cache.profile, "get_profile", mock_get_profile)
    monkeypatch.setattr(Cache.client, "get_client", mock_get_client)
    monkeypatch.setattr(Cache.workout, "get_latest_subscription", mock_get_subscription)

    request: HttpRequest = HttpRequest()
    request.method = "GET"
    request.GET = {"init_data": "data"}

    response: JsonResponse = await views.subscription_data(request)
    assert response.status_code == 503
