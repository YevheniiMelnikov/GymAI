import sys
from importlib import import_module
from types import SimpleNamespace

import pytest
from django.http import HttpRequest, JsonResponse

from core.cache import Cache
from core.enums import CoachType

django_http = sys.modules["django.http"]
django_http.HttpResponse = object  # type: ignore[attr-defined]
django_shortcuts = sys.modules.setdefault("django.shortcuts", SimpleNamespace(render=lambda *a, **k: None))

views = import_module("apps.webapp.views")


@pytest.mark.asyncio
async def test_programs_history_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def mock_get_profile(tg_id: int, *, use_fallback: bool = True) -> SimpleNamespace:
        return SimpleNamespace(id=1)

    async def mock_get_all_programs(profile_id: int) -> list[SimpleNamespace]:
        return [SimpleNamespace(id=1, created_at=1.0, coach_type=CoachType.ai)]

    monkeypatch.setattr(views, "verify_init_data", lambda _d: {"user": {"id": 1}})
    monkeypatch.setattr(Cache.profile, "get_profile", mock_get_profile)
    monkeypatch.setattr(Cache.workout, "get_all_programs", mock_get_all_programs)

    request: HttpRequest = HttpRequest()
    request.method = "GET"
    request.GET = {"init_data": "data"}

    response: JsonResponse = await views.programs_history(request)
    assert response.status_code == 200
    assert response["programs"][0]["id"] == 1
    assert response["programs"][0]["coach_type"] == CoachType.ai


@pytest.mark.asyncio
async def test_programs_history_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_error(_d: str) -> dict[str, object]:
        raise ValueError

    monkeypatch.setattr(views, "verify_init_data", raise_error)

    request: HttpRequest = HttpRequest()
    request.method = "GET"
    request.GET = {"init_data": "bad"}

    response: JsonResponse = await views.programs_history(request)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_programs_history_server_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def mock_get_profile(tg_id: int, *, use_fallback: bool = True) -> SimpleNamespace:
        raise RuntimeError("boom")

    monkeypatch.setattr(views, "verify_init_data", lambda _d: {"user": {"id": 1}})
    monkeypatch.setattr(Cache.profile, "get_profile", mock_get_profile)

    request: HttpRequest = HttpRequest()
    request.method = "GET"
    request.GET = {"init_data": "data"}

    response: JsonResponse = await views.programs_history(request)
    assert response.status_code == 500
