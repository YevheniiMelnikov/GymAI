import os
import time
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import cast

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from loguru import logger
from rest_framework.exceptions import NotFound

from apps.payments.repos import PaymentRepository
from apps.workout_plans.repos import ProgramRepository, SubscriptionRepository
from core.schemas import Program, Subscription

from .utils import (
    auth_and_get_client,
    build_payment_gateway,
    call_repo,
    ensure_container_ready,
    parse_program_id,
)

STATIC_VERSION_FILE: Path = Path(__file__).resolve().parents[2] / "VERSION"


def _resolve_static_version() -> str:
    env_value: str | None = os.getenv("STATIC_VERSION")
    if STATIC_VERSION_FILE.exists():
        version: str = STATIC_VERSION_FILE.read_text(encoding="utf-8").strip()
        if version:
            return version
    if env_value:
        return env_value
    return str(int(time.time()))


STATIC_VERSION: str = _resolve_static_version()


def _transform_days(exercises_by_day: list) -> list[dict]:
    days = []
    for idx, day_data in enumerate(exercises_by_day, start=1):
        exercises = []
        for ex_idx, ex_data in enumerate(day_data.get("exercises", [])):
            weight_str = ex_data.get("weight")
            weight = None
            if weight_str:
                parts = str(weight_str).split(" ", 1)
                if len(parts) == 2:
                    weight = {"value": parts[0], "unit": parts[1]}
                else:
                    weight = {"value": weight_str, "unit": ""}

            exercises.append({
                "id": str(ex_data.get("set_id") or f"ex-{idx}-{ex_idx}"),
                "name": ex_data.get("name", ""),
                "sets": ex_data.get("sets"),
                "reps": ex_data.get("reps"),
                "weight": weight,
                "equipment": None,
                "notes": None,
            })

        days.append({
            "id": f"day-{idx}",
            "index": idx,
            "type": "workout",
            "title": day_data.get("day"),
            "exercises": exercises,
        })
    return days


# type checking of async views with require_GET is not supported by stubs
@require_GET  # type: ignore[misc]
async def program_data(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    source_raw = request.GET.get("source", "direct")
    source: str = str(source_raw or "direct")
    if source not in {"direct", "subscription"}:
        logger.warning(f"Unsupported program source={source}")
        source = "direct"

    program_id, pid_error = parse_program_id(request)
    if pid_error:
        return pid_error

    try:
        client, lang, auth_error, _tg = await auth_and_get_client(request)
    except Exception:
        logger.exception("Auth resolution failed")
        return JsonResponse({"error": "server_error"}, status=500)
    if auth_error:
        return auth_error
    assert client is not None

    client_id = int(getattr(client, "id", 0))

    if source == "subscription":
        subscription_obj: Subscription | None = cast(
            Subscription | None,
            await call_repo(SubscriptionRepository.get_latest, client_id),
        )
        if subscription_obj is None:
            logger.warning(f"Subscription not found for client_profile_id={client.id}")
            return JsonResponse({"error": "not_found"}, status=404)

        # Use the same transformation for subscription data
        days = _transform_days(subscription_obj.exercises)
        return JsonResponse({"days": days, "id": str(subscription_obj.id), "language": lang})

    program_obj: Program | None = cast(
        Program | None,
        await call_repo(ProgramRepository.get_by_id, client_id, program_id)
        if program_id is not None
        else await call_repo(ProgramRepository.get_latest, client_id),
    )

    if program_obj is None:
        logger.warning(f"Program not found for client_profile_id={client.id} program_id={program_id}")
        # Debug logging
        latest = await call_repo(ProgramRepository.get_latest, client_id)
        all_programs = await call_repo(ProgramRepository.filter_by_client, client_id)
        logger.info(f"DEBUG: client_id={client_id} program_id={program_id} latest_program={latest.id if latest else 'None'}")
        logger.info(f"DEBUG: all_program_ids={[p.id for p in all_programs] if all_programs else 'None'}")
        print(f"DEBUG PRINT: client_id={client_id} program_id={program_id} latest_program={latest.id if latest else 'None'}")
        return JsonResponse({"error": "not_found"}, status=404)

    data = {
        "created_at": int(cast(datetime, program_obj.created_at).timestamp()),
        "coach_type": program_obj.coach_type,
        "language": lang,
    }

    if isinstance(program_obj.exercises_by_day, list):
        data["days"] = _transform_days(program_obj.exercises_by_day)
        data["id"] = str(program_obj.id)
        data["locale"] = lang
    else:
        data["program"] = program_obj.exercises_by_day

    return JsonResponse(data)


# type checking of async views with require_GET is not supported by stubs
@require_GET  # type: ignore[misc]
async def programs_history(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    try:
        client, lang, auth_error, tg_id = await auth_and_get_client(request)
    except Exception:
        logger.exception("Auth resolution failed")
        return JsonResponse({"error": "server_error"}, status=500)
    if auth_error:
        return auth_error
    assert client is not None

    try:
        programs = cast(
            list[Program],
            await call_repo(ProgramRepository.get_all, int(getattr(client, "id", 0))),
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
        client, lang, auth_error, _tg = await auth_and_get_client(request)
    except Exception:
        logger.exception("Auth resolution failed")
        return JsonResponse({"error": "server_error"}, status=500)
    if auth_error:
        return auth_error
    assert client is not None

    subscription = cast(
        Subscription | None,
        await call_repo(SubscriptionRepository.get_latest, int(getattr(client, "id", 0))),
    )
    if subscription is None:
        logger.warning(f"Subscription not found for client_profile_id={client.id}")
        return JsonResponse({"error": "not_found"}, status=404)

    days = _transform_days(subscription.exercises)
    return JsonResponse({"days": days, "id": str(subscription.id), "language": lang})


# type checking of async views with require_GET is not supported by stubs
@require_GET  # type: ignore[misc]
async def payment_data(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    order_raw = request.GET.get("order_id", "")
    order_id: str = str(order_raw or "").strip()
    if not order_id:
        logger.warning("Payment data requested without order_id")
        return JsonResponse({"error": "bad_request"}, status=400)

    try:
        client, lang, auth_error, tg_id = await auth_and_get_client(request)
    except Exception:
        logger.exception("Auth resolution failed")
        return JsonResponse({"error": "server_error"}, status=500)
    if auth_error:
        return auth_error
    assert client is not None

    try:
        payment = await call_repo(PaymentRepository.get_by_order_id, order_id)
    except Exception as exc:
        if exc.__class__ is NotFound:
            logger.warning(f"Payment not found for order_id={order_id} tg_id={tg_id}")
            return JsonResponse({"error": "not_found"}, status=404)
        raise

    client_profile_id = int(getattr(client, "id", 0))
    payment_client_id = int(getattr(payment, "client_profile_id", 0))
    if payment_client_id != client_profile_id:
        logger.warning(
            f"Payment order_id={order_id} belongs to client_profile_id={payment_client_id}, "
            f"requested by {client_profile_id}"
        )
        return JsonResponse({"error": "not_found"}, status=404)

    gateway = build_payment_gateway()
    amount_value = Decimal(str(getattr(payment, "amount", "0"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    checkout = gateway.build_checkout(
        "pay",
        amount_value,
        order_id,
        str(getattr(payment, "payment_type", "")),
        client_profile_id,
    )

    return JsonResponse(
        {
            "data": checkout.data,
            "signature": checkout.signature,
            "checkout_url": checkout.checkout_url,
            "amount": str(amount_value),
            "currency": "UAH",
            "payment_type": getattr(payment, "payment_type", ""),
            "language": lang,
        }
    )


def index(request: HttpRequest) -> HttpResponse:
    logger.info(f"Webapp hit: {request.method} {request.get_full_path()}")
    return render(request, "webapp/index.html", {"static_version": STATIC_VERSION})


def ping(request: HttpRequest) -> HttpResponse:
    logger.info(f"Webapp ping: {request.method} {request.get_full_path()}")
    return HttpResponse("ok")
