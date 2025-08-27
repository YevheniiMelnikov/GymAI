from django.http import JsonResponse, HttpRequest, HttpResponse
from django.shortcuts import render

from core.cache import Cache
from core.exceptions import (
    ProfileNotFoundError,
    ProgramNotFoundError,
    SubscriptionNotFoundError,
    ClientNotFoundError,
    UserServiceError,
)
from loguru import logger
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
        profile = await Cache.profile.get_profile(tg_id)
        client = await Cache.client.get_client(profile.id)
        if program_id is not None:
            program = await Cache.workout.get_program_by_id(client.id, int(program_id))
        else:
            program = await Cache.workout.get_latest_program(client.id)
    except (ProfileNotFoundError, ClientNotFoundError, ProgramNotFoundError):
        logger.warning("Program not found for tg_id={}", tg_id)
        return JsonResponse({"error": "not_found"}, status=404)
    except UserServiceError as exc:
        logger.warning("Workout service unavailable for tg_id={}: {}", tg_id, exc)
        return JsonResponse({"error": "service_unavailable"}, status=200)
    except Exception:
        logger.exception("Failed to fetch program for tg_id={}", tg_id)
        return JsonResponse({"error": "server_error"}, status=500)
    text: str = _format_full_program(program.exercises_by_day)
    return JsonResponse(
        {
            "program": text,
            "created_at": program.created_at,
            "coach_type": program.coach_type,
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
        profile = await Cache.profile.get_profile(tg_id)
        client = await Cache.client.get_client(profile.id)
        programs = await Cache.workout.get_all_programs(client.id)
    except (ProfileNotFoundError, ClientNotFoundError, ProgramNotFoundError):
        logger.warning("Programs not found for tg_id={}", tg_id)
        return JsonResponse({"error": "not_found"}, status=404)
    except UserServiceError as exc:
        logger.warning("Workout service unavailable for tg_id={}: {}", tg_id, exc)
        return JsonResponse({"error": "service_unavailable"}, status=200)
    except Exception:
        logger.exception("Failed to fetch programs for tg_id={}", tg_id)
        return JsonResponse({"error": "server_error"}, status=500)
    items = [{"id": p.id, "created_at": p.created_at, "coach_type": p.coach_type} for p in programs]
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
        profile = await Cache.profile.get_profile(tg_id)
        client = await Cache.client.get_client(profile.id)
        subscription = await Cache.workout.get_latest_subscription(client.id)
    except (ProfileNotFoundError, ClientNotFoundError, SubscriptionNotFoundError):
        logger.warning("Subscription not found for tg_id={}", tg_id)
        return JsonResponse({"error": "not_found"}, status=404)
    except UserServiceError as exc:
        logger.warning("Workout service unavailable for tg_id={}: {}", tg_id, exc)
        return JsonResponse({"error": "service_unavailable"}, status=200)
    except Exception:
        logger.exception("Failed to fetch subscription for tg_id={}", tg_id)
        return JsonResponse({"error": "server_error"}, status=500)
    text: str = _format_full_program(subscription.exercises)
    return JsonResponse({"program": text})


def index(request: HttpRequest) -> HttpResponse:
    logger.info("Webapp hit: {} {}", request.method, request.get_full_path())
    return render(request, "webapp/index.html")


def ping(request: HttpRequest) -> HttpResponse:
    logger.info("Webapp ping: {} {}", request.method, request.get_full_path())
    return HttpResponse("ok")
