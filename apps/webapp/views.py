from django.http import JsonResponse, HttpRequest, HttpResponse
from django.shortcuts import render

from asgiref.sync import sync_to_async
from loguru import logger
from rest_framework.exceptions import NotFound

from apps.profiles.repos import ProfileRepository, ClientProfileRepository
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
        profile = await sync_to_async(ProfileRepository.get_by_telegram_id)(tg_id)
        client = await sync_to_async(ClientProfileRepository.get)(profile.id)
        if program_id is not None:
            program_obj = await sync_to_async(ProgramRepository.get_by_id)(client.id, int(program_id))
        else:
            program_obj = await sync_to_async(ProgramRepository.get_latest)(client.id)
        if program_obj is None:
            raise NotFound
    except NotFound:
        logger.warning("Program not found for tg_id={}", tg_id)
        return JsonResponse({"error": "not_found"}, status=404)
    except Exception:
        logger.exception("Failed to fetch program for tg_id={}", tg_id)
        return JsonResponse({"error": "server_error"}, status=500)
    exercises = [DayExercises.model_validate(e) for e in program_obj.exercises_by_day or []]
    text: str = _format_full_program(exercises)
    return JsonResponse(
        {
            "program": text,
            "created_at": program_obj.created_at.timestamp(),
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
        profile = await sync_to_async(ProfileRepository.get_by_telegram_id)(tg_id)
        client = await sync_to_async(ClientProfileRepository.get)(profile.id)
        programs = await sync_to_async(ProgramRepository.get_all)(client.id)
    except NotFound:
        logger.warning("Programs not found for tg_id={}", tg_id)
        return JsonResponse({"error": "not_found"}, status=404)
    except Exception:
        logger.exception("Failed to fetch programs for tg_id={}", tg_id)
        return JsonResponse({"error": "server_error"}, status=500)
    items = [{"id": p.id, "created_at": p.created_at.timestamp(), "coach_type": p.coach_type} for p in programs]
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
        profile = await sync_to_async(ProfileRepository.get_by_telegram_id)(tg_id)
        client = await sync_to_async(ClientProfileRepository.get)(profile.id)
        subscription = await sync_to_async(SubscriptionRepository.get_latest)(client.id)
        if subscription is None:
            raise NotFound
    except NotFound:
        logger.warning("Subscription not found for tg_id={}", tg_id)
        return JsonResponse({"error": "not_found"}, status=404)
    except Exception:
        logger.exception("Failed to fetch subscription for tg_id={}", tg_id)
        return JsonResponse({"error": "server_error"}, status=500)
    exercises = [DayExercises.model_validate(e) for e in subscription.exercises or []]
    text: str = _format_full_program(exercises)
    return JsonResponse({"program": text})


def index(request: HttpRequest) -> HttpResponse:
    logger.info("Webapp hit: {} {}", request.method, request.get_full_path())
    return render(request, "webapp/index.html")


def ping(request: HttpRequest) -> HttpResponse:
    logger.info("Webapp ping: {} {}", request.method, request.get_full_path())
    return HttpResponse("ok")
