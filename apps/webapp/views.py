from django.http import JsonResponse, HttpRequest, HttpResponse
from django.shortcuts import render

from core.cache import Cache
from core.schemas import DayExercises
from loguru import logger
from .utils import verify_init_data


def _format_full_program(exercises: list[DayExercises]) -> str:
    lines: list[str] = []
    for day in sorted(exercises, key=lambda d: int(d.day)):
        lines.append(f"Day {day.day}")
        for idx, ex in enumerate(day.exercises):
            line = f"{idx + 1}. {ex.name} | {ex.sets} x {ex.reps}"
            if ex.weight:
                line += f" | {ex.weight} kg"
            if ex.set_id is not None:
                line += f" | Set {ex.set_id}"
            if ex.drop_set:
                line += " | Drop set"
            lines.append(line)
        lines.append("")
    return "\n".join(lines).strip()


async def program_data(request):
    init_data = request.GET.get("init_data", "")
    logger.debug("Webapp program data requested: init_data length={}", len(init_data))
    try:
        data = verify_init_data(init_data)
    except Exception:
        return JsonResponse({"error": "unauthorized"}, status=403)

    user = data.get("user", {})
    tg_id = int(user.get("id", 0))
    try:
        profile = await Cache.profile.get_profile(tg_id)
        program = await Cache.workout.get_latest_program(profile.id)
        text = _format_full_program(program.exercises_by_day)
    except Exception:
        text = ""
    return JsonResponse({"program": text})


async def subscription_data(request):
    init_data = request.GET.get("init_data", "")
    logger.debug("Webapp subscription data requested: init_data length={}", len(init_data))
    try:
        data = verify_init_data(init_data)
    except Exception:
        return JsonResponse({"error": "unauthorized"}, status=403)

    user = data.get("user", {})
    tg_id = int(user.get("id", 0))
    try:
        profile = await Cache.profile.get_profile(tg_id)
        subscription = await Cache.workout.get_latest_subscription(profile.id)
        text = _format_full_program(subscription.exercises)
    except Exception:
        text = ""
    return JsonResponse({"program": text})


def index(request: HttpRequest) -> HttpResponse:
    logger.info("Webapp hit: {} {}", request.method, request.get_full_path())
    return render(request, "webapp/index.html")


def ping(request: HttpRequest) -> HttpResponse:
    logger.info("Webapp ping: {} {}", request.method, request.get_full_path())
    return HttpResponse("ok")
