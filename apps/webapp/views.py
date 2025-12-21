import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, cast

import httpx
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from loguru import logger
from rest_framework.exceptions import NotFound

from apps.payments.repos import PaymentRepository
from apps.workout_plans.models import Program as ProgramModel
from apps.workout_plans.repos import ProgramRepository, SubscriptionRepository
from config.app_settings import settings
from core.internal_http import build_internal_hmac_auth_headers, internal_request_timeout
from core.schemas import Program as ProgramSchema, Subscription
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
    logger.info(f"program_data_request profile_id={profile.id} source={source} program_id={program_id}")
    try:
        total_programs = await call_repo(lambda pid: ProgramModel.objects.filter(profile_id=pid).count(), profile.id)
    except Exception:
        total_programs = -1
    logger.info(f"program_db_stats profile_id={profile.id} total_programs={total_programs}")

    if source == "subscription":
        subscription_obj: Subscription | None = cast(
            Subscription | None,
            await call_repo(SubscriptionRepository.get_latest, profile.id),
        )
        if subscription_obj is None:
            return JsonResponse({"error": "not_found"}, status=404)

        days = transform_days(subscription_obj.exercises)
        return JsonResponse({"days": days, "id": str(subscription_obj.id), "language": profile.language})

    program_obj: ProgramModel | ProgramSchema | None = None
    try:
        program_obj = cast(
            ProgramSchema | None,
            await call_repo(ProgramRepository.get_by_id, profile.id, program_id)
            if program_id is not None
            else await call_repo(ProgramRepository.get_latest, profile.id),
        )
    except Exception:
        logger.exception(f"Failed to load program from repo profile_id={profile.id} program_id={program_id}")

    if program_obj is None:
        try:
            all_programs = cast(list[ProgramSchema], await call_repo(ProgramRepository.get_all, profile.id))
            program_obj = all_programs[0] if all_programs else None
        except Exception:
            logger.exception(f"Fallback load of all programs failed profile_id={profile.id}")

    if program_obj is None:
        try:
            program_obj = await call_repo(
                lambda pid: ProgramModel.objects.filter(profile_id=pid).order_by("-created_at", "-id").first(),
                profile.id,
            )
            if program_obj is None:
                await call_repo(lambda pid: ProgramModel.objects.filter(profile_id=pid).count(), profile.id)
            else:
                program_pk = getattr(program_obj, "id", None)
                logger.info(f"Program loaded via direct ORM profile_id={profile.id} program_id={program_pk}")
        except Exception:
            logger.exception(f"Direct program lookup failed profile_id={profile.id}")

    if isinstance(program_obj, ProgramModel):
        try:
            program_obj = ProgramSchema.model_validate(program_obj)
        except Exception:
            logger.exception(f"Failed to normalize ProgramModel for profile_id={profile.id}")
            program_obj = None

    if program_obj is None:
        return JsonResponse({"error": "not_found"}, status=404)

    created_raw = getattr(program_obj, "created_at", None)
    created_at = 0
    if isinstance(created_raw, datetime):
        created_at = int(created_raw.timestamp())
    else:
        try:
            created_at = int(float(created_raw or 0))
        except (TypeError, ValueError):
            try:
                created_at = int(datetime.fromisoformat(str(created_raw)).timestamp())
            except Exception:
                created_at = 0

    data: dict[str, object] = {
        "created_at": created_at,
        "language": profile.language,
    }

    program_id_value = getattr(program_obj, "id", None)
    if isinstance(program_obj.exercises_by_day, list):
        days_payload: list[dict[str, Any]] = []
        for item in program_obj.exercises_by_day:
            if hasattr(item, "model_dump"):
                days_payload.append(item.model_dump())
            elif isinstance(item, dict):
                days_payload.append(item)
        if not days_payload:
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
            list[ProgramSchema],
            await call_repo(ProgramRepository.get_all, int(getattr(profile, "id", 0))),
        )
    except Exception:
        logger.exception(f"Failed to fetch programs for profile_id={profile.id}")
        return JsonResponse({"error": "server_error"}, status=500)

    try:
        subscriptions = cast(
            list[Subscription],
            await call_repo(SubscriptionRepository.get_all, int(getattr(profile, "id", 0))),
        )
    except Exception:
        logger.exception(f"Failed to fetch subscriptions for profile_id={profile.id}")
        subscriptions = []

    items = [
        {
            "id": int(p.id),
            "created_at": int(cast(datetime, p.created_at).timestamp()),
        }
        for p in programs
    ]
    subscription_items: list[dict[str, int]] = []
    for subscription in subscriptions:
        updated_raw = getattr(subscription, "updated_at", None)
        updated_at = 0
        if isinstance(updated_raw, datetime):
            updated_at = int(updated_raw.timestamp())
        else:
            try:
                updated_at = int(float(updated_raw or 0))
            except (TypeError, ValueError):
                try:
                    updated_at = int(datetime.fromisoformat(str(updated_raw)).timestamp())
                except Exception:
                    updated_at = 0

        subscription_items.append(
            {
                "id": int(getattr(subscription, "id", 0)),
                "created_at": updated_at,
            }
        )

    return JsonResponse(
        {
            "programs": items,
            "subscriptions": subscription_items,
            "language": profile.language,
        }
    )


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


@csrf_exempt  # type: ignore[bad-specialization]
@require_POST  # type: ignore[misc]
async def workouts_action(request: HttpRequest) -> JsonResponse:
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
        payload = json.loads(request.body or "{}")
    except Exception:
        logger.warning("workouts_action_invalid_payload")
        return JsonResponse({"error": "bad_request"}, status=400)

    action = str(payload.get("action") or "")
    if action not in {"create_program", "create_subscription"}:
        return JsonResponse({"error": "bad_request"}, status=400)

    profile_dump = {
        "id": profile.id,
        "tg_id": profile.tg_id,
        "language": profile.language or settings.DEFAULT_LANG,
        "status": profile.status,
    }
    logger.info(f"workouts_action_request profile_id={profile.id} action={action}")

    raw_base_url = (settings.BOT_INTERNAL_URL or "").rstrip("/")
    fallback_base = f"http://{settings.BOT_INTERNAL_HOST}:{settings.BOT_INTERNAL_PORT}"
    base_url = raw_base_url or fallback_base
    logger.debug(f"workouts_action_internal_base profile_id={profile.id} base_url={base_url}")

    proxy_payload = {
        "action": action,
        "profile_id": profile.id,
        "telegram_id": profile.tg_id,
        "profile": profile_dump,
    }
    body = json.dumps(proxy_payload).encode("utf-8")
    try:
        headers = build_internal_hmac_auth_headers(
            key_id=settings.INTERNAL_KEY_ID,
            secret_key=settings.INTERNAL_API_KEY,
            body=body,
        )
    except Exception:
        logger.exception("Failed to build internal auth headers for workouts_action")
        return JsonResponse({"error": "server_error"}, status=500)
    headers["Content-Type"] = "application/json"

    timeout = internal_request_timeout(settings)

    async def _post(target_url: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.post(target_url, content=body, headers=headers)

    primary_url = f"{base_url}/internal/webapp/workouts/action/"
    try:
        resp = await _post(primary_url)
    except httpx.HTTPError as exc:
        logger.error(f"workouts_action_call_failed profile_id={profile.id} base_url={base_url} err={exc}")
        if base_url != fallback_base:
            fallback_url = f"{fallback_base}/internal/webapp/workouts/action/"
            logger.info(f"workouts_action_retrying_fallback profile_id={profile.id} fallback={fallback_base}")
            try:
                resp = await _post(fallback_url)
            except httpx.HTTPError as exc2:
                logger.error(f"workouts_action_call_failed profile_id={profile.id} fallback={fallback_base} err={exc2}")
                return JsonResponse({"error": "server_error"}, status=502)
        else:
            return JsonResponse({"error": "server_error"}, status=502)

    if resp.status_code >= 400:
        logger.warning(
            (
                f"workouts_action_rejected profile_id={profile.id} action={action} "
                f"status={resp.status_code} body={resp.text[:200]}"
            )
        )
        if resp.status_code == 400:
            return JsonResponse({"error": "bad_request"}, status=400)
        if resp.status_code == 404:
            return JsonResponse({"error": "not_found"}, status=404)
        if resp.status_code == 503:
            return JsonResponse({"error": "service_unavailable"}, status=503)
        return JsonResponse({"error": "server_error"}, status=502)

    logger.info(f"workouts_action_dispatched profile_id={profile.id} action={action}")
    return JsonResponse({"status": "ok"})


def index(request: HttpRequest) -> HttpResponse:
    logger.info(f"Webapp hit: {request.method} {request.get_full_path()}")
    return render(request, "webapp/index.html", {"static_version": STATIC_VERSION})


def ping(request: HttpRequest) -> HttpResponse:
    logger.info(f"Webapp ping: {request.method} {request.get_full_path()}")
    return HttpResponse("ok")
