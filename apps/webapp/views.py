from typing import Any, Tuple, cast
from datetime import datetime

from django.http import JsonResponse, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from asgiref.sync import sync_to_async
from loguru import logger
from rest_framework.exceptions import NotFound

from apps.profiles.models import ClientProfile, Profile
from apps.profiles.repos import ClientProfileRepository, ProfileRepository
from apps.workout_plans.models import Program, Subscription
from apps.workout_plans.repos import ProgramRepository, SubscriptionRepository
from core.schemas import DayExercises
from .utils import (
    verify_init_data,
    _format_full_program,
    ensure_container_ready,
    normalize_day_exercises,
)


async def _auth_and_get_client(
    request: HttpRequest,
) -> Tuple[ClientProfile | None, str, JsonResponse | None, int]:
    """
    Verify Telegram init_data, resolve tg_id -> Profile -> ClientProfile.

    Returns (client | None, language, error_response | None, tg_id).
    """
    init_data: str = str(request.GET.get("init_data", ""))
    logger.debug(f"Webapp request: init_data length={len(init_data)}")
    lang: str = "eng"
    try:
        data: dict[str, Any] = verify_init_data(init_data)
    except Exception as exc:
        logger.warning(f"Init data verification failed: {exc} | length={len(init_data)}")
        return None, lang, JsonResponse({"error": "unauthorized"}, status=403), 0

    user: dict[str, Any] = data.get("user", {})  # type: ignore[arg-type]
    tg_id: int = int(str(user.get("id", "0")))

    try:
        profile: Profile = await sync_to_async(ProfileRepository.get_by_telegram_id)(tg_id)
    except NotFound:
        logger.warning(f"Profile not found for tg_id={tg_id}")
        return None, lang, JsonResponse({"error": "not_found"}, status=404), tg_id

    lang = str(getattr(profile, "language", "eng") or "eng")
    try:
        client: ClientProfile = await sync_to_async(ClientProfileRepository.get_by_profile_id)(int(profile.pk))
    except NotFound:
        logger.warning(f"Client profile not found for profile_id={profile.pk}")
        return None, lang, JsonResponse({"error": "not_found"}, status=404), tg_id

    return client, lang, None, tg_id


def _parse_program_id(request: HttpRequest) -> Tuple[int | None, JsonResponse | None]:
    raw = cast(str | None, request.GET.get("program_id"))
    if not raw:
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

    client, lang, auth_error, _tg = await _auth_and_get_client(request)
    if auth_error:
        return auth_error
    assert client is not None

    program_id, pid_error = _parse_program_id(request)
    if pid_error:
        return pid_error

    if program_id is not None:
        program_obj: Program | None = await sync_to_async(ProgramRepository.get_by_id)(int(client.pk), program_id)
    else:
        program_obj = await sync_to_async(ProgramRepository.get_latest)(int(client.pk))

    if program_obj is None:
        logger.warning(f"Program not found for client_profile_id={client.pk} program_id={program_id}")
        return JsonResponse({"error": "not_found"}, status=404)

    text: str = _format_program_text(program_obj.exercises_by_day)
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

    client, lang, auth_error, tg_id = await _auth_and_get_client(request)
    if auth_error:
        return auth_error
    assert client is not None

    try:
        programs: list[Program] = await sync_to_async(ProgramRepository.get_all)(int(client.pk))
    except Exception:
        logger.exception(f"Failed to fetch programs for tg_id={tg_id}")
        return JsonResponse({"error": "server_error"}, status=500)

    items = [
        {
            "id": int(p.pk),
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

    client, lang, auth_error, _tg = await _auth_and_get_client(request)
    if auth_error:
        return auth_error
    assert client is not None

    subscription: Subscription | None = await sync_to_async(SubscriptionRepository.get_latest)(int(client.pk))
    if subscription is None:
        logger.warning(f"Subscription not found for client_profile_id={client.pk}")
        return JsonResponse({"error": "not_found"}, status=404)

    text: str = _format_program_text(subscription.exercises)
    return JsonResponse({"program": text, "language": lang})


def index(request: HttpRequest) -> HttpResponse:
    logger.info(f"Webapp hit: {request.method} {request.get_full_path()}")
    return render(request, "webapp/index.html")


def ping(request: HttpRequest) -> HttpResponse:
    logger.info(f"Webapp ping: {request.method} {request.get_full_path()}")
    return HttpResponse("ok")
