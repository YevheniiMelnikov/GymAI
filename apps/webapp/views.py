from django.http import JsonResponse, HttpRequest, HttpResponse
from django.shortcuts import render

from asgiref.sync import sync_to_async
from loguru import logger
from rest_framework.exceptions import NotFound

from apps.profiles.models import ClientProfile, Profile
from apps.profiles.repos import ClientProfileRepository, ProfileRepository
from apps.workout_plans.models import Program, Subscription
from apps.workout_plans.repos import ProgramRepository, SubscriptionRepository
from core.schemas import DayExercises
from .utils import verify_init_data, _format_full_program, ensure_container_ready


async def program_data(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()
    init_data: str = str(request.GET.get("init_data", ""))
    logger.debug("Webapp program data requested: init_data length={}", len(init_data))
    try:
        data: dict[str, object] = verify_init_data(init_data)
    except Exception as exc:
        logger.warning(
            "Init data verification failed: {} | length={}",
            exc,
            len(init_data),
        )
        return JsonResponse({"error": "unauthorized"}, status=403)

    user: dict[str, object] = data.get("user", {})  # type: ignore[arg-type]
    tg_id: int = int(str(user.get("id", "0")))
    program_id: str | None = request.GET.get("program_id")

    try:
        profile: Profile = await sync_to_async(ProfileRepository.get_by_telegram_id)(tg_id)
    except NotFound:
        logger.warning("Profile not found for tg_id={}", tg_id)
        return JsonResponse({"error": "not_found"}, status=404)

    try:
        client: ClientProfile = await sync_to_async(ClientProfileRepository.get_by_profile_id)(profile.id)
    except NotFound:
        logger.warning("Client profile not found for profile_id={}", profile.id)
        return JsonResponse({"error": "not_found"}, status=404)

    if program_id is not None:
        program_obj: Program | None = await sync_to_async(ProgramRepository.get_by_id)(client.id, int(program_id))
    else:
        program_obj = await sync_to_async(ProgramRepository.get_latest)(client.id)

    if program_obj is None:
        logger.warning(
            "Program not found for client_profile_id={} program_id={}",
            client.id,
            program_id,
        )
        return JsonResponse({"error": "not_found"}, status=404)

    exercises = [DayExercises.model_validate(e) for e in program_obj.exercises_by_day or []]
    text: str = _format_full_program(exercises)
    return JsonResponse(
        {
            "program": text,
            "created_at": int(program_obj.created_at.timestamp()),
            "coach_type": program_obj.coach_type,
        }
    )


async def programs_history(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()
    init_data: str = str(request.GET.get("init_data", ""))
    logger.debug("Webapp programs history requested: init_data length={}", len(init_data))
    try:
        data: dict[str, object] = verify_init_data(init_data)
    except Exception as exc:
        logger.warning(
            "Init data verification failed: {} | length={}",
            exc,
            len(init_data),
        )
        return JsonResponse({"error": "unauthorized"}, status=403)

    user: dict[str, object] = data.get("user", {})  # type: ignore[arg-type]
    tg_id: int = int(str(user.get("id", "0")))

    try:
        profile: Profile = await sync_to_async(ProfileRepository.get_by_telegram_id)(tg_id)
    except NotFound:
        logger.warning("Profile not found for tg_id={}", tg_id)
        return JsonResponse({"error": "not_found"}, status=404)

    try:
        client: ClientProfile = await sync_to_async(ClientProfileRepository.get_by_profile_id)(profile.id)
    except NotFound:
        logger.warning("Client profile not found for profile_id={}", profile.id)
        return JsonResponse({"error": "not_found"}, status=404)

    try:
        programs: list[Program] = await sync_to_async(ProgramRepository.get_all)(client.id)
    except Exception:
        logger.exception("Failed to fetch programs for tg_id={}", tg_id)
        return JsonResponse({"error": "server_error"}, status=500)

    items = [{"id": p.id, "created_at": int(p.created_at.timestamp()), "coach_type": p.coach_type} for p in programs]
    return JsonResponse({"programs": items})


async def subscription_data(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()
    init_data: str = str(request.GET.get("init_data", ""))
    logger.debug("Webapp subscription data requested: init_data length={}", len(init_data))
    try:
        data: dict[str, object] = verify_init_data(init_data)
    except Exception as exc:
        logger.warning(
            "Init data verification failed: {} | length={}",
            exc,
            len(init_data),
        )
        return JsonResponse({"error": "unauthorized"}, status=403)

    user: dict[str, object] = data.get("user", {})  # type: ignore[arg-type]
    tg_id: int = int(str(user.get("id", "0")))

    try:
        profile: Profile = await sync_to_async(ProfileRepository.get_by_telegram_id)(tg_id)
    except NotFound:
        logger.warning("Profile not found for tg_id={}", tg_id)
        return JsonResponse({"error": "not_found"}, status=404)

    try:
        client: ClientProfile = await sync_to_async(ClientProfileRepository.get_by_profile_id)(profile.id)
    except NotFound:
        logger.warning("Client profile not found for profile_id={}", profile.id)
        return JsonResponse({"error": "not_found"}, status=404)

    subscription: Subscription | None = await sync_to_async(SubscriptionRepository.get_latest)(client.id)
    if subscription is None:
        logger.warning("Subscription not found for client_profile_id={}", client.id)
        return JsonResponse({"error": "not_found"}, status=404)

    exercises = [DayExercises.model_validate(e) for e in subscription.exercises or []]
    text: str = _format_full_program(exercises)
    return JsonResponse({"program": text})


def index(request: HttpRequest) -> HttpResponse:
    logger.info("Webapp hit: {} {}", request.method, request.get_full_path())
    return render(request, "webapp/index.html")


def ping(request: HttpRequest) -> HttpResponse:
    logger.info("Webapp ping: {} {}", request.method, request.get_full_path())
    return HttpResponse("ok")
