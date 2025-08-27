import sys
from importlib import import_module
from types import SimpleNamespace

import pytest
from django.http import HttpRequest, JsonResponse


django_http = sys.modules["django.http"]
django_http.HttpResponse = object  # type: ignore[attr-defined]
django_shortcuts = sys.modules.setdefault("django.shortcuts", SimpleNamespace(render=lambda *a, **k: None))

views = import_module("apps.webapp.views")


@pytest.mark.asyncio
async def test_subscription_data_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(views, "verify_init_data", lambda _d: {"user": {"id": 1}})
    monkeypatch.setattr(
        views.ProfileRepository,
        "get_by_telegram_id",
        lambda _tg_id: SimpleNamespace(id=1),
    )
    monkeypatch.setattr(
        views.ClientProfileRepository,
        "get_by_profile_id",
        lambda _id: SimpleNamespace(id=1),
    )
    monkeypatch.setattr(
        views.SubscriptionRepository,
        "get_latest",
        lambda _id: SimpleNamespace(exercises=[]),
    )

    request: HttpRequest = HttpRequest()
    request.method = "GET"
    request.GET = {"init_data": "data"}

    response: JsonResponse = await views.subscription_data(request)
    assert response.status_code == 200
    assert response["program"] == ""


@pytest.mark.asyncio
async def test_subscription_data_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(views, "verify_init_data", lambda _d: {"user": {"id": 1}})
    monkeypatch.setattr(
        views.ProfileRepository,
        "get_by_telegram_id",
        lambda _tg_id: SimpleNamespace(id=1),
    )
    monkeypatch.setattr(
        views.ClientProfileRepository,
        "get_by_profile_id",
        lambda _id: SimpleNamespace(id=1),
    )
    monkeypatch.setattr(
        views.SubscriptionRepository,
        "get_latest",
        lambda _id: None,
    )

    request: HttpRequest = HttpRequest()
    request.method = "GET"
    request.GET = {"init_data": "data"}

    response: JsonResponse = await views.subscription_data(request)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_subscription_data_server_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(views, "verify_init_data", lambda _d: {"user": {"id": 1}})
    monkeypatch.setattr(
        views.ProfileRepository,
        "get_by_telegram_id",
        lambda _tg_id: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    request: HttpRequest = HttpRequest()
    request.method = "GET"
    request.GET = {"init_data": "data"}

    response: JsonResponse = await views.subscription_data(request)
    assert response.status_code == 500
