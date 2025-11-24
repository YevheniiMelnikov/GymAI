import asyncio
import json
import sys
from importlib import import_module
from types import SimpleNamespace
from datetime import datetime

import pytest
from django.http import HttpRequest, JsonResponse

from apps.webapp import utils

django_http = sys.modules["django.http"]
django_http.HttpResponse = object  # type: ignore[attr-defined]
django_shortcuts = sys.modules.setdefault("django.shortcuts", SimpleNamespace(render=lambda *a, **k: None))

views = import_module("apps.webapp.views")


def test_programs_history_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        async def noop_ready() -> None:
            return None

        monkeypatch.setattr(utils, "ensure_container_ready", noop_ready)
        monkeypatch.setattr(views, "ensure_container_ready", noop_ready)
        monkeypatch.setattr("apps.webapp.utils.verify_init_data", lambda _d: {"user": {"id": 1}})
        monkeypatch.setattr(
            utils.ProfileRepository,
            "get_by_telegram_id",
            lambda _tg_id: SimpleNamespace(id=1, language="eng"),
        )
        monkeypatch.setattr(
            utils.ProfileRepository,
            "get_by_profile_id",
            lambda _id: SimpleNamespace(id=1),
        )
        monkeypatch.setattr(
            views.ProgramRepository,
            "get_all",
            lambda _id: [SimpleNamespace(id=1, created_at=datetime.fromtimestamp(1))],
        )

        request: HttpRequest = HttpRequest()
        request.method = "GET"
        request.GET = {"init_data": "data"}

        response: JsonResponse = await views.programs_history(request)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["programs"][0]["id"] == 1
        assert data["language"] == "eng"

    asyncio.run(runner())


def test_programs_history_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        def raise_error(_d: str) -> dict[str, object]:
            raise ValueError

        monkeypatch.setattr("apps.webapp.utils.verify_init_data", raise_error)

        request: HttpRequest = HttpRequest()
        request.method = "GET"
        request.GET = {"init_data": "bad"}

        response: JsonResponse = await views.programs_history(request)
        assert response.status_code == 403

    asyncio.run(runner())


def test_programs_history_server_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        monkeypatch.setattr("apps.webapp.utils.verify_init_data", lambda _d: {"user": {"id": 1}})
        monkeypatch.setattr(
            utils.ProfileRepository,
            "get_by_telegram_id",
            lambda _tg_id: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        request: HttpRequest = HttpRequest()
        request.method = "GET"
        request.GET = {"init_data": "data"}

        response: JsonResponse = await views.programs_history(request)
        assert response.status_code == 500

    asyncio.run(runner())
