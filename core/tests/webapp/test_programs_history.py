import sys
from importlib import import_module
from types import SimpleNamespace
from datetime import datetime

import pytest
from django.http import HttpRequest, JsonResponse

from core.enums import CoachType

django_http = sys.modules["django.http"]
django_http.HttpResponse = object  # type: ignore[attr-defined]
django_shortcuts = sys.modules.setdefault("django.shortcuts", SimpleNamespace(render=lambda *a, **k: None))

views = import_module("apps.webapp.views")


@pytest.mark.asyncio
async def test_programs_history_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(views, "verify_init_data", lambda _d: {"user": {"id": 1}})
    monkeypatch.setattr(
        views.ProfileRepository,
        "get_by_telegram_id",
        lambda _tg_id: SimpleNamespace(id=1, language="eng"),
    )
    monkeypatch.setattr(
        views.ClientProfileRepository,
        "get_by_profile_id",
        lambda _id: SimpleNamespace(id=1),
    )
    monkeypatch.setattr(
        views.ProgramRepository,
        "get_all",
        lambda _id: [SimpleNamespace(id=1, created_at=datetime.fromtimestamp(1), coach_type=CoachType.ai_coach)],
    )

    request: HttpRequest = HttpRequest()
    request.method = "GET"
    request.GET = {"init_data": "data"}

    response: JsonResponse = await views.programs_history(request)
    assert response.status_code == 200
    assert response["programs"][0]["id"] == 1
    assert response["programs"][0]["coach_type"] == CoachType.ai_coach
    assert response["language"] == "eng"


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
    monkeypatch.setattr(views, "verify_init_data", lambda _d: {"user": {"id": 1}})
    monkeypatch.setattr(
        views.ProfileRepository,
        "get_by_telegram_id",
        lambda _tg_id: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    request: HttpRequest = HttpRequest()
    request.method = "GET"
    request.GET = {"init_data": "data"}

    response: JsonResponse = await views.programs_history(request)
    assert response.status_code == 500
