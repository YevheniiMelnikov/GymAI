from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, cast

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from loguru import logger
from rest_framework.exceptions import NotFound

from apps.payments.repos import PaymentRepository
from apps.workout_plans.repos import ProgramRepository, SubscriptionRepository
from core.schemas import Program, Subscription
from .utils import STATIC_VERSION, transform_days

from .utils import (
    authenticate,
    build_payment_gateway,
    call_repo,
    ensure_container_ready,
    parse_program_id,
)


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
        auth_ctx = await authenticate(request)
    except Exception:
        logger.exception("Auth resolution failed")
        return JsonResponse({"error": "server_error"}, status=500)
    if auth_ctx.error:
        return auth_ctx.error
    profile = auth_ctx.profile
    if profile is None:
        return JsonResponse({"error": "not_found"}, status=404)

    if source == "subscription":
        subscription_obj: Subscription | None = cast(
            Subscription | None,
            await call_repo(SubscriptionRepository.get_latest, profile.id),
        )
        if subscription_obj is None:
            logger.warning(f"Subscription not found for profile_id={profile.id}")
            return JsonResponse({"error": "not_found"}, status=404)

        days = transform_days(subscription_obj.exercises)
        return JsonResponse({"days": days, "id": str(subscription_obj.id), "language": profile.language})

    program_obj: Program | None = cast(
        Program | None,
        await call_repo(ProgramRepository.get_by_id, profile.id, program_id)
        if program_id is not None
        else await call_repo(ProgramRepository.get_latest, profile.id),
    )

    if program_obj is None:
        logger.warning(f"Program not found for profile_id={profile.id} program_id={program_id}")
        return JsonResponse({"error": "not_found"}, status=404)

    data: dict[str, object] = {
        "created_at": int(cast(datetime, program_obj.created_at).timestamp()),
        "language": profile.language,
    }

    program_id_value = getattr(program_obj, "id", None)
    if isinstance(program_obj.exercises_by_day, list):
        days_payload = cast(list[dict[str, Any]], program_obj.exercises_by_day)
        transformed = transform_days(days_payload)
        data["days"] = transformed
        data["program"] = transformed
        if program_id_value is not None:
            data["id"] = str(program_id_value)
        elif program_id is not None:
            data["id"] = str(program_id)
        data["locale"] = profile.language
    else:
        data["program"] = program_obj.exercises_by_day

    return JsonResponse(data)


# type checking of async views with require_GET is not supported by stubs
@require_GET  # type: ignore[misc]
async def programs_history(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    try:
        auth_ctx = await authenticate(request)
    except Exception:
        logger.exception("Auth resolution failed")
        return JsonResponse({"error": "server_error"}, status=500)
    if auth_ctx.error:
        return auth_ctx.error
    profile = auth_ctx.profile
    if profile is None:
        return JsonResponse({"error": "not_found"}, status=404)

    try:
        programs = cast(
            list[Program],
            await call_repo(ProgramRepository.get_all, int(getattr(profile, "id", 0))),
        )
    except Exception:
        logger.exception(f"Failed to fetch programs for profile_id={profile.id}")
        return JsonResponse({"error": "server_error"}, status=500)

    items = [
        {
            "id": int(p.id),
            "created_at": int(cast(datetime, p.created_at).timestamp()),
        }
        for p in programs
    ]
    return JsonResponse({"programs": items, "language": profile.language})


# type checking of async views with require_GET is not supported by stubs
@require_GET  # type: ignore[misc]
async def subscription_data(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    try:
        auth_ctx = await authenticate(request)
    except Exception:
        logger.exception("Auth resolution failed")
        return JsonResponse({"error": "server_error"}, status=500)
    if auth_ctx.error:
        return auth_ctx.error
    profile = auth_ctx.profile
    if profile is None:
        return JsonResponse({"error": "not_found"}, status=404)

    subscription = cast(
        Subscription | None,
        await call_repo(SubscriptionRepository.get_latest, int(getattr(profile, "id", 0))),
    )
    if subscription is None:
        logger.warning(f"Subscription not found for profile_id={profile.id}")
        return JsonResponse({"error": "not_found"}, status=404)

    subscription_id = getattr(subscription, "id", None)
    days = transform_days(subscription.exercises)
    response: dict[str, object] = {"days": days, "language": profile.language, "program": days}
    if subscription_id is not None:
        response["id"] = str(subscription_id)
    return JsonResponse(response)


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
        auth_ctx = await authenticate(request)
    except Exception:
        logger.exception("Auth resolution failed")
        return JsonResponse({"error": "server_error"}, status=500)
    if auth_ctx.error:
        return auth_ctx.error
    profile = auth_ctx.profile
    if profile is None:
        return JsonResponse({"error": "not_found"}, status=404)

    try:
        payment = await call_repo(PaymentRepository.get_by_order_id, order_id)
    except Exception as exc:
        if exc.__class__ is NotFound:
            logger.warning(f"Payment not found for order_id={order_id} profile_id={profile.id}")
            return JsonResponse({"error": "not_found"}, status=404)
        raise

    profile_id = int(getattr(profile, "id", 0))
    payment_profile_id = int(getattr(payment, "profile_id", 0))
    if payment_profile_id != profile_id:
        logger.warning(
            f"Payment order_id={order_id} belongs to profile_id={payment_profile_id}, requested by {profile_id}"
        )
        return JsonResponse({"error": "not_found"}, status=404)

    gateway = build_payment_gateway()
    amount_value = Decimal(str(getattr(payment, "amount", "0"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    checkout = gateway.build_checkout(
        "pay",
        amount_value,
        order_id,
        str(getattr(payment, "payment_type", "")),
        profile_id,
    )

    return JsonResponse(
        {
            "data": checkout.data,
            "signature": checkout.signature,
            "checkout_url": checkout.checkout_url,
            "amount": str(amount_value),
            "currency": "UAH",
            "payment_type": getattr(payment, "payment_type", ""),
            "language": profile.language,
        }
    )


def index(request: HttpRequest) -> HttpResponse:
    logger.info(f"Webapp hit: {request.method} {request.get_full_path()}")
    return render(request, "webapp/index.html", {"static_version": STATIC_VERSION})


def ping(request: HttpRequest) -> HttpResponse:
    logger.info(f"Webapp ping: {request.method} {request.get_full_path()}")
    return HttpResponse("ok")
