from __future__ import annotations

from typing import Any, Tuple

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


async def _auth_and_get_client(request: HttpRequest) -> Tuple[ClientProfile | None, JsonResponse | None, int]:
    """
    Verify Telegram init_data, resolve tg_id -> Profile -> ClientProfile.
    Returns (client | None, error_response | None, tg_id).
    """
    init_data: str = str(request.GET.get("init_data", ""))
    logger.debug("Webapp request: init_data length={}", len(init_data))
    try:
        data: dict[str, Any] = verify_init_data(init_data)
    except Exception as exc:
        logger.warning("Init data verification failed: {} | length={}", exc, len(init_data))
        return None, JsonResponse({"error": "unauthorized"}, status=403), 0

    user: dict[str, Any] = data.get("user", {})  # type: ignore[arg-type]
    tg_id: int = int(str(user.get("id", "0")))

    try:
        profile: Profile = await sync_to_async(ProfileRepository.get_by_telegram_id)(tg_id)
    except NotFound:
        logger.warning("Profile not found for tg_id={}", tg_id)
        return None, JsonResponse({"error": "not_found"}, status=404), tg_id

    try:
        client: ClientProfile = await sync_to_async(ClientProfileRepository.get_by_profile_id)(profile.id)
    except NotFound:
        logger.warning("Client profile not found for profile_id={}", profile.id)
        return None, JsonResponse({"error": "not_found"}, status=404), tg_id

    return client, None, tg_id


def _parse_program_id(request: HttpRequest) -> Tuple[int | None, JsonResponse | None]:
    raw: str | None = request.GET.get("program_id")
    if not raw:
        return None, None
    try:
        return int(raw), None
    except ValueError:
        logger.warning("Invalid program_id={}", raw)
        return None, JsonResponse({"error": "bad_request"}, status=400)


def _format_program_text(raw_exercises: Any) -> str:
    raw = normalize_day_exercises(raw_exercises)
    exercises = [DayExercises.model_validate(e) for e in raw]
    return _format_full_program(exercises)


@require_GET
async def program_data(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    client, auth_error, _tg = await _auth_and_get_client(request)
    if auth_error:
        return auth_error
    assert client is not None

    program_id, pid_error = _parse_program_id(request)
    if pid_error:
        return pid_error

    if program_id is not None:
        program_obj: Program | None = await sync_to_async(ProgramRepository.get_by_id)(client.id, program_id)
    else:
        program_obj = await sync_to_async(ProgramRepository.get_latest)(client.id)

    if program_obj is None:
        logger.warning(
            "Program not found for client_profile_id={} program_id={}",
            client.id,
            program_id,
        )
        return JsonResponse({"error": "not_found"}, status=404)

    text: str = _format_program_text(program_obj.exercises_by_day)
    return JsonResponse(
        {
            "program": text,
            "created_at": int(program_obj.created_at.timestamp()),
            "coach_type": program_obj.coach_type,
        }
    )


@require_GET
async def programs_history(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    client, auth_error, tg_id = await _auth_and_get_client(request)
    if auth_error:
        return auth_error
    assert client is not None

    try:
        programs: list[Program] = await sync_to_async(ProgramRepository.get_all)(client.id)
    except Exception:
        logger.exception("Failed to fetch programs for tg_id={}", tg_id)
        return JsonResponse({"error": "server_error"}, status=500)

    items = [{"id": p.id, "created_at": int(p.created_at.timestamp()), "coach_type": p.coach_type} for p in programs]
    return JsonResponse({"programs": items})


@require_GET
async def subscription_data(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    client, auth_error, _tg = await _auth_and_get_client(request)
    if auth_error:
        return auth_error
    assert client is not None

    subscription: Subscription | None = await sync_to_async(SubscriptionRepository.get_latest)(client.id)
    if subscription is None:
        logger.warning("Subscription not found for client_profile_id={}", client.id)
        return JsonResponse({"error": "not_found"}, status=404)

    text: str = _format_program_text(subscription.exercises)
    return JsonResponse({"program": text})


def index(request: HttpRequest) -> HttpResponse:
    logger.info("Webapp hit: {} {}", request.method, request.get_full_path())
    return render(request, "webapp/index.html")


def ping(request: HttpRequest) -> HttpResponse:
    logger.info("Webapp ping: {} {}", request.method, request.get_full_path())
    return HttpResponse("ok")
