from __future__ import annotations

import inspect
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Tuple, TypeVar, TYPE_CHECKING, cast, Protocol

from asgiref.sync import sync_to_async
from django.http import JsonResponse, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from loguru import logger
from rest_framework.exceptions import NotFound

from core.schemas import DayExercises, Program, Subscription
from .utils import (
    verify_init_data,
    _format_full_program,
    ensure_container_ready,
    normalize_day_exercises,
)


class _Profile(Protocol):
    id: int | None
    language: str | None


class _ClientProfile(Protocol):
    id: int | None


if TYPE_CHECKING:
    from apps.profiles.repos import ClientProfileRepository, ProfileRepository
    from apps.workout_plans.repos import ProgramRepository, SubscriptionRepository
else:  # attributes for monkeypatching in tests

    class _RepoStub(SimpleNamespace):
        pass

    try:
        from apps.profiles.repos import ClientProfileRepository as _ClientProfileRepo
        from apps.profiles.repos import ProfileRepository as _ProfileRepo
        from apps.workout_plans.repos import (
            ProgramRepository as _ProgramRepo,
            SubscriptionRepository as _SubscriptionRepo,
        )
    except Exception:  # pragma: no cover - fall back to stubs in exceptional cases
        _ClientProfileRepo = _RepoStub(get_by_profile_id=lambda *a, **k: None)
        _ProfileRepo = _RepoStub(get_by_telegram_id=lambda *a, **k: None)
        _ProgramRepo = _RepoStub(
            get_latest=lambda *a, **k: None,
            get_by_id=lambda *a, **k: None,
            get_all=lambda *a, **k: [],
        )
        _SubscriptionRepo = _RepoStub(get_latest=lambda *a, **k: None)

    ClientProfileRepository = _ClientProfileRepo
    ProfileRepository = _ProfileRepo
    ProgramRepository = _ProgramRepo
    SubscriptionRepository = _SubscriptionRepo

T = TypeVar("T")


async def _call_repo(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Execute repository call regardless of sync_to_async stubbing."""
    result = sync_to_async(func)(*args, **kwargs)
    if inspect.isawaitable(result):
        return await cast(Awaitable[T], result)
    return cast(T, result)


def _read_init_data(request: HttpRequest) -> str:
    init_data_raw = request.GET.get("init_data", "")
    init_data: str = str(init_data_raw or "")
    if init_data:
        return init_data

    headers = getattr(request, "headers", None)
    if headers is not None:
        header_value = headers.get("X-Telegram-InitData")
        if header_value:
            return str(header_value)

    meta_value = request.META.get("HTTP_X_TELEGRAM_INITDATA")
    if isinstance(meta_value, str):
        return meta_value
    return ""


async def _auth_and_get_client(
    request: HttpRequest,
) -> Tuple[_ClientProfile | None, str, JsonResponse | None, int]:
    """
    Verify Telegram init_data, resolve tg_id -> Profile -> ClientProfile.

    Returns (client | None, language, error_response | None, tg_id).
    """
    init_data: str = _read_init_data(request)
    logger.debug(f"Webapp request: init_data length={len(init_data)}")
    lang: str = "eng"
    try:
        data: dict[str, Any] = verify_init_data(init_data)
    except Exception as exc:
        logger.warning(f"Init data verification failed: {exc} | length={len(init_data)}")
        return None, lang, JsonResponse({"error": "unauthorized"}, status=403), 0

    user: dict[str, Any] = data.get("user", {})  # type: ignore[arg-type]
    tg_id: int = int(str(user.get("id", "0")))

    global ClientProfileRepository, ProfileRepository

    try:
        profile = cast(_Profile, await _call_repo(ProfileRepository.get_by_telegram_id, tg_id))
    except Exception as exc:
        if exc.__class__ is NotFound:
            logger.warning(f"Profile not found for tg_id={tg_id}")
            return None, lang, JsonResponse({"error": "not_found"}, status=404), tg_id
        raise

    lang = str(getattr(profile, "language", "eng") or "eng")
    try:
        client = cast(
            _ClientProfile,
            await _call_repo(ClientProfileRepository.get_by_profile_id, int(profile.id or 0)),
        )
    except Exception as exc:
        if exc.__class__ is NotFound:
            logger.warning(f"Client profile not found for profile_id={profile.id}")
            return None, lang, JsonResponse({"error": "not_found"}, status=404), tg_id
        raise

    return client, lang, None, tg_id


def _parse_program_id(request: HttpRequest) -> Tuple[int | None, JsonResponse | None]:
    raw = request.GET.get("program_id")
    if not isinstance(raw, str) or not raw:
        return None, None
    try:
        return int(raw), None
    except ValueError:
        logger.warning(f"Invalid program_id={raw}")
        return None, JsonResponse({"error": "bad_request"}, status=400)


def _format_program_text(raw_exercises: Any) -> str:
    raw = normalize_day_exercises(raw_exercises)
    exercises = [DayExercises.model_validate(e) for e in raw]
    return _format_full_program(exercises)


# type checking of async views with require_GET is not supported by stubs
@require_GET  # type: ignore[misc]
async def program_data(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    source_raw = request.GET.get("source", "direct")
    source: str = str(source_raw or "direct")
    if source not in {"direct", "subscription"}:
        logger.warning(f"Unsupported program source={source}")
        source = "direct"

    program_id, pid_error = _parse_program_id(request)
    if pid_error:
        return pid_error

    try:
        client, lang, auth_error, _tg = await _auth_and_get_client(request)
    except Exception:
        logger.exception("Auth resolution failed")
        return JsonResponse({"error": "server_error"}, status=500)
    if auth_error:
        return auth_error
    assert client is not None

    global ProgramRepository, SubscriptionRepository

    client_id = int(getattr(client, "id", 0))

    if source == "subscription":
        subscription_obj: Subscription | None = cast(
            Subscription | None,
            await _call_repo(SubscriptionRepository.get_latest, client_id),
        )
        if subscription_obj is None:
            logger.warning(f"Subscription not found for client_profile_id={client.id}")
            return JsonResponse({"error": "not_found"}, status=404)

        text: str = _format_program_text(subscription_obj.exercises)
        return JsonResponse({"program": text, "language": lang})

    program_obj: Program | None = cast(
        Program | None,
        await _call_repo(ProgramRepository.get_by_id, client_id, program_id)
        if program_id is not None
        else await _call_repo(ProgramRepository.get_latest, client_id),
    )

    if program_obj is None:
        logger.warning(f"Program not found for client_profile_id={client.id} program_id={program_id}")
        return JsonResponse({"error": "not_found"}, status=404)

    text = _format_program_text(program_obj.exercises_by_day)
    return JsonResponse(
        {
            "program": text,
            "created_at": int(cast(datetime, program_obj.created_at).timestamp()),
            "coach_type": program_obj.coach_type,
            "language": lang,
        }
    )


# type checking of async views with require_GET is not supported by stubs
@require_GET  # type: ignore[misc]
async def programs_history(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    try:
        client, lang, auth_error, tg_id = await _auth_and_get_client(request)
    except Exception:
        logger.exception("Auth resolution failed")
        return JsonResponse({"error": "server_error"}, status=500)
    if auth_error:
        return auth_error
    assert client is not None

    global ProgramRepository

    try:
        programs = cast(
            list[Program],
            await _call_repo(ProgramRepository.get_all, int(getattr(client, "id", 0))),
        )
    except Exception:
        logger.exception(f"Failed to fetch programs for tg_id={tg_id}")
        return JsonResponse({"error": "server_error"}, status=500)

    items = [
        {
            "id": int(p.id),
            "created_at": int(cast(datetime, p.created_at).timestamp()),
            "coach_type": p.coach_type,
        }
        for p in programs
    ]
    return JsonResponse({"programs": items, "language": lang})


# type checking of async views with require_GET is not supported by stubs
@require_GET  # type: ignore[misc]
async def subscription_data(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    try:
        client, lang, auth_error, _tg = await _auth_and_get_client(request)
    except Exception:
        logger.exception("Auth resolution failed")
        return JsonResponse({"error": "server_error"}, status=500)
    if auth_error:
        return auth_error
    assert client is not None

    global SubscriptionRepository

    subscription = cast(
        Subscription | None,
        await _call_repo(SubscriptionRepository.get_latest, int(getattr(client, "id", 0))),
    )
    if subscription is None:
        logger.warning(f"Subscription not found for client_profile_id={client.id}")
        return JsonResponse({"error": "not_found"}, status=404)

    text: str = _format_program_text(subscription.exercises)
    return JsonResponse({"program": text, "language": lang})


def index(request: HttpRequest) -> HttpResponse:
    logger.info(f"Webapp hit: {request.method} {request.get_full_path()}")
    return render(request, "webapp/index.html")


def ping(request: HttpRequest) -> HttpResponse:
    logger.info(f"Webapp ping: {request.method} {request.get_full_path()}")
    return HttpResponse("ok")
