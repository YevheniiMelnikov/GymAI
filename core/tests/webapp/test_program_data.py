import asyncio
import json
import sys
from importlib import import_module
from types import SimpleNamespace
from datetime import datetime

import pytest
from django.http import HttpRequest, JsonResponse

from rest_framework.exceptions import NotFound
from core.enums import CoachType
from apps.webapp import utils

django_http = sys.modules["django.http"]
django_http.HttpResponse = object  # type: ignore[attr-defined]
django_shortcuts = sys.modules.setdefault("django.shortcuts", SimpleNamespace(render=lambda *a, **k: None))

views = import_module("apps.webapp.views")


def test_program_data_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        monkeypatch.setattr("apps.webapp.utils.verify_init_data", lambda _d: {"user": {"id": 1}})
        monkeypatch.setattr(
            utils.ProfileRepository,
            "get_by_telegram_id",
            lambda _tg_id: SimpleNamespace(id=1, language="eng"),
        )
        monkeypatch.setattr(
            utils.ClientProfileRepository,
            "get_by_profile_id",
            lambda _id: SimpleNamespace(id=1),
        )
        monkeypatch.setattr(
            views.ProgramRepository,
            "get_latest",
            lambda _id: SimpleNamespace(
                exercises_by_day=[],
                created_at=datetime.fromtimestamp(1),
                coach_type=CoachType.human,
            ),
        )

        request: HttpRequest = HttpRequest()
        request.method = "GET"
        request.GET = {"init_data": "data"}

        response: JsonResponse = await views.program_data(request)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["program"] == []
        assert data["created_at"] == 1
        assert data["coach_type"] == CoachType.human
        assert data["language"] == "eng"

    asyncio.run(runner())


def test_program_data_header_init_data(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        captured: dict[str, str] = {}

        def fake_verify(data: str) -> dict[str, object]:
            captured["value"] = data
            return {"user": {"id": 1}}

        monkeypatch.setattr("apps.webapp.utils.verify_init_data", fake_verify)
        monkeypatch.setattr(
            utils.ProfileRepository,
            "get_by_telegram_id",
            lambda _tg_id: SimpleNamespace(id=1, language="eng"),
        )
        monkeypatch.setattr(
            utils.ClientProfileRepository,
            "get_by_profile_id",
            lambda _id: SimpleNamespace(id=1),
        )
        monkeypatch.setattr(
            views.ProgramRepository,
            "get_latest",
            lambda _id: SimpleNamespace(
                exercises_by_day=[],
                created_at=datetime.fromtimestamp(1),
                coach_type=CoachType.human,
            ),
        )

        request: HttpRequest = HttpRequest()
        request.method = "GET"
        request.GET = {}
        request.META = {}
        request.META["HTTP_X_TELEGRAM_INITDATA"] = "header_data"

        response: JsonResponse = await views.program_data(request)
        assert response.status_code == 200
        assert captured.get("value") == "header_data"

    asyncio.run(runner())


def test_program_data_with_id(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        monkeypatch.setattr("apps.webapp.utils.verify_init_data", lambda _d: {"user": {"id": 1}})
        monkeypatch.setattr(
            utils.ProfileRepository,
            "get_by_telegram_id",
            lambda _tg_id: SimpleNamespace(id=1, language="eng"),
        )
        monkeypatch.setattr(
            utils.ClientProfileRepository,
            "get_by_profile_id",
            lambda _id: SimpleNamespace(id=1),
        )
        monkeypatch.setattr(
            views.ProgramRepository,
            "get_by_id",
            lambda _cid, _pid: SimpleNamespace(
                exercises_by_day=[],
                created_at=datetime.fromtimestamp(2),
                coach_type=CoachType.human,
            ),
        )

        request: HttpRequest = HttpRequest()
        request.method = "GET"
        request.GET = {"init_data": "data", "program_id": "5"}

        response: JsonResponse = await views.program_data(request)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["created_at"] == 2
        assert data["coach_type"] == CoachType.human
        assert data["language"] == "eng"

    asyncio.run(runner())


def test_program_data_bad_id(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        monkeypatch.setattr("apps.webapp.utils.verify_init_data", lambda _d: {"user": {"id": 1}})

        request: HttpRequest = HttpRequest()
        request.method = "GET"
        request.GET = {"init_data": "data", "program_id": "bad"}

        response: JsonResponse = await views.program_data(request)
        assert response.status_code == 400

    asyncio.run(runner())


def test_program_data_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        def raise_error(_d: str) -> dict[str, object]:
            raise ValueError

        monkeypatch.setattr("apps.webapp.utils.verify_init_data", raise_error)

        request: HttpRequest = HttpRequest()
        request.method = "GET"
        request.GET = {"init_data": "bad"}

        response: JsonResponse = await views.program_data(request)
        assert response.status_code == 403

    asyncio.run(runner())


def test_program_data_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    async def runner() -> None:
        monkeypatch.setattr("apps.webapp.utils.verify_init_data", lambda _d: {"user": {"id": 1}})
        monkeypatch.setattr(
            utils.ProfileRepository,
            "get_by_telegram_id",
            lambda _tg_id: (_ for _ in ()).throw(NotFound("missing")),
        )

        request: HttpRequest = HttpRequest()
        request.method = "GET"
        request.GET = {"init_data": "data"}

        response: JsonResponse = await views.program_data(request)
        assert response.status_code == 404

    asyncio.run(runner())


def test_program_data_server_error(monkeypatch: pytest.MonkeyPatch) -> None:
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

        response: JsonResponse = await views.program_data(request)
        assert response.status_code == 500

    asyncio.run(runner())
