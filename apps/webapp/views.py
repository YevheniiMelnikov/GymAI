import json
from decimal import Decimal, ROUND_HALF_UP
from typing import cast
from uuid import uuid4
from django.http import HttpRequest, HttpResponse, JsonResponse
from google.api_core.exceptions import NotFound as GCSNotFound
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from loguru import logger
from pydantic import ValidationError
from rest_framework.exceptions import NotFound

from apps.payments.models import Payment
from apps.payments.repos import PaymentRepository
from apps.diet_plans.repos import DietPlanRepository
from apps.workout_plans.models import Program as ProgramModel
from apps.workout_plans.repos import ProgramRepository, SubscriptionRepository
from apps.webapp.weekly_survey import (
    WeeklySurveyPayload,
    SurveyFeedbackContext,
    build_weekly_survey_feedback,
    enqueue_subscription_update,
    resolve_plan_age_weeks,
)
from apps.profiles.choices import ProfileStatus
from apps.profiles.models import Profile
from apps.profiles.repos import ProfileRepository
from apps.profiles.serializers import ProfileSerializer
from config.app_settings import settings
from core.internal_http import build_internal_hmac_auth_headers, internal_request_timeout
from core.cache import Cache
from core.enums import WorkoutLocation, PaymentStatus, WorkoutPlanType
from core.schemas import Program as ProgramSchema, Subscription
from django.core.cache import cache
from core.ai_coach.exercise_catalog import load_exercise_catalog
from core.ai_coach.exercise_catalog.technique_loader import get_exercise_technique
from core.services.gstorage_service import ExerciseGIFStorage
from core.tasks.ai_coach.replace_exercise import (
    enqueue_exercise_replace_task,
    enqueue_subscription_exercise_replace_task,
)
from apps.webapp.exercise_replace import (
    ExerciseSetPayload,
    UpdateExercisePayload,
    UpdateSubscriptionExercisePayload,
    apply_sets_update,
    consume_program_replace_limit,
    consume_subscription_replace_limit,
    is_aux_exercise_entry,
    parse_sets_payload,
    resolve_exercise_entry,
)
from .utils import STATIC_VERSION, transform_days
from .utils import (
    build_payment_gateway,
    call_repo,
    ensure_container_ready,
    parse_program_id,
    parse_subscription_id,
    resolve_credit_package,
    resolve_workout_location,
    validate_internal_hmac,
    workout_plan_pricing,
)
from .view_helpers import (
    atomic_debit_credits,
    build_days_payload,
    build_profile_payload,
    build_support_contact_payload,
    build_webapp_profile_payload,
    build_workout_plan_options_payload,
    create_subscription_record,
    fetch_program,
    parse_bool,
    parse_profile_updates,
    parse_timestamp,
    post_internal_request,
    resolve_internal_base_url,
    resolve_profile,
    resolve_workout_plan_required,
)
from .schemas import DietPlanSavePayload
from core.services import APIService
from .workout_flow import WorkoutPlanRequest, enqueue_workout_plan_generation
from .diet_flow import enqueue_diet_plan_generation


def _parse_diet_id(request: HttpRequest) -> tuple[int | None, JsonResponse | None]:
    raw = request.GET.get("diet_id")
    if not isinstance(raw, str) or not raw:
        return None, None
    try:
        return int(raw), None
    except ValueError:
        logger.warning(f"Invalid diet_id={raw}")
        return None, JsonResponse({"error": "bad_request"}, status=400)


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

    profile_or_error = await resolve_profile(request, log_request=False)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error
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

        days = transform_days(subscription_obj.exercises, language=profile.language)
        return JsonResponse({"days": days, "id": str(subscription_obj.id), "language": profile.language})

    program_obj = await fetch_program(profile.id, program_id)

    if program_obj is None:
        return JsonResponse({"error": "not_found"}, status=404)

    created_at = parse_timestamp(getattr(program_obj, "created_at", None))

    data: dict[str, object] = {
        "created_at": created_at,
        "language": profile.language,
    }

    program_id_value = getattr(program_obj, "id", None)
    if isinstance(program_obj.exercises_by_day, list):
        days_payload = build_days_payload(program_obj.exercises_by_day)
        transformed = transform_days(days_payload, language=profile.language)
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


@require_GET  # type: ignore[misc]
def exercise_gif(request: HttpRequest, gif_key: str) -> HttpResponse:
    safe_key = str(gif_key or "").strip().lstrip("/")
    if not safe_key:
        return HttpResponse(status=404)

    entries = load_exercise_catalog()
    if entries and safe_key not in {entry.gif_key for entry in entries}:
        logger.warning(f"exercise_gif_rejected gif_key={safe_key}")
        return HttpResponse(status=404)

    storage = ExerciseGIFStorage(settings.EXERCISE_GIF_BUCKET)
    if storage.bucket is None:
        logger.warning("exercise_gif_storage_unavailable")
        return HttpResponse(status=404)

    blob = storage.bucket.blob(safe_key)
    try:
        content = blob.download_as_bytes()
    except GCSNotFound:
        logger.warning(f"exercise_gif_missing gif_key={safe_key}")
        return HttpResponse(status=404)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"exercise_gif_failed gif_key={safe_key} detail={exc}")
        return HttpResponse(status=502)

    response = HttpResponse(content, content_type=blob.content_type or "image/gif")
    response["Cache-Control"] = "public, max-age=3600"
    return response


@require_GET  # type: ignore[misc]
def exercise_technique(request: HttpRequest, gif_key: str) -> JsonResponse:
    safe_key = str(gif_key or "").strip().lstrip("/")
    if not safe_key:
        return JsonResponse({"error": "not_found"}, status=404)

    entries = load_exercise_catalog()
    if entries and safe_key not in {entry.gif_key for entry in entries}:
        logger.warning(f"exercise_technique_rejected gif_key={safe_key}")
        return JsonResponse({"error": "not_found"}, status=404)

    lang = request.GET.get("lang") or request.GET.get("locale")
    technique = get_exercise_technique(safe_key, str(lang) if lang is not None else None)
    if technique is None:
        return JsonResponse({"error": "not_found"}, status=404)

    return JsonResponse(
        {
            "gif_key": safe_key,
            "canonical_name": technique.canonical_name,
            "technique_description": list(technique.technique_description),
        }
    )


# type checking of async views with require_GET is not supported by stubs
@require_GET  # type: ignore[misc]
async def programs_history(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error
    if getattr(profile, "status", None) == ProfileStatus.deleted:
        return JsonResponse({"error": "not_found"}, status=404)

    try:
        programs = cast(
            list[ProgramSchema],
            await call_repo(ProgramRepository.get_all, int(getattr(profile, "id", 0))),
        )
    except Exception:
        profile_id = getattr(profile, "id", "unknown")
        logger.exception(f"Failed to fetch programs for profile_id={profile_id}")
        return JsonResponse({"error": "server_error"}, status=500)

    try:
        subscriptions = cast(
            list[Subscription],
            await call_repo(SubscriptionRepository.get_all, int(getattr(profile, "id", 0))),
        )
    except Exception:
        profile_id = getattr(profile, "id", "unknown")
        logger.exception(f"Failed to fetch subscriptions for profile_id={profile_id}")
        subscriptions = []

    items = [
        {
            "id": int(p.id),
            "created_at": parse_timestamp(getattr(p, "created_at", None)),
        }
        for p in programs
    ]
    subscription_items: list[dict[str, int]] = []
    for subscription in subscriptions:
        subscription_items.append(
            {
                "id": int(getattr(subscription, "id", 0)),
                "created_at": parse_timestamp(getattr(subscription, "updated_at", None)),
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

    subscription_id, id_error = parse_subscription_id(request)
    if id_error:
        return id_error

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error

    if subscription_id is not None:
        subscription = cast(
            Subscription | None,
            await call_repo(SubscriptionRepository.get_by_id, int(getattr(profile, "id", 0)), subscription_id),
        )
    else:
        subscription = cast(
            Subscription | None,
            await call_repo(SubscriptionRepository.get_latest, int(getattr(profile, "id", 0))),
        )
    if subscription is None:
        return JsonResponse({"error": "not_found"}, status=404)

    exercises = subscription.exercises if isinstance(subscription.exercises, list) else []
    if not exercises:
        return JsonResponse({"error": "not_found"}, status=404)

    subscription_id = getattr(subscription, "id", None)
    days = transform_days(exercises, language=profile.language)
    response: dict[str, object] = {
        "days": days,
        "language": profile.language,
        "program": days,
        "created_at": parse_timestamp(getattr(subscription, "updated_at", None)),
    }
    if subscription_id is not None:
        response["id"] = str(subscription_id)
    return JsonResponse(response)


@require_GET  # type: ignore[misc]
async def subscription_status(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error

    active = cast(
        Subscription | None,
        await call_repo(
            lambda pid: SubscriptionRepository.base_qs()
            .filter(profile_id=pid, enabled=True)
            .order_by("-updated_at")
            .first(),
            int(getattr(profile, "id", 0)),
        ),
    )
    response: dict[str, object] = {"active": bool(active)}
    if active is not None:
        response["id"] = str(getattr(active, "id", ""))
    return JsonResponse(response)


# type checking of async views with require_GET is not supported by stubs
@csrf_exempt  # type: ignore[bad-specialization]
@require_POST  # type: ignore[misc]
async def payment_init(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error

    try:
        payload = json.loads(request.body or "{}")
    except Exception:
        logger.warning("payment_init_invalid_payload")
        return JsonResponse({"error": "bad_request"}, status=400)

    if not isinstance(payload, dict):
        return JsonResponse({"error": "bad_request"}, status=400)

    package_id = payload.get("package_id")
    if not isinstance(package_id, str) or not package_id.strip():
        return JsonResponse({"error": "bad_request"}, status=400)

    package = resolve_credit_package(package_id)
    if package is None:
        logger.warning(f"payment_init_unknown_package package_id={package_id} profile_id={profile.id}")
        return JsonResponse({"error": "bad_request"}, status=400)

    order_id = uuid4().hex
    amount_value = Decimal(package.price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    try:
        await call_repo(
            Payment.objects.create,
            payment_type="credits",
            profile_id=profile.id,
            order_id=order_id,
            amount=amount_value,
            status=PaymentStatus.PENDING.value,
            processed=False,
        )
    except Exception:
        logger.exception(f"payment_init_create_failed profile_id={profile.id} package_id={package.package_id}")
        return JsonResponse({"error": "server_error"}, status=500)

    gateway = build_payment_gateway()
    checkout = gateway.build_checkout(
        "pay",
        amount_value,
        order_id,
        "credits",
        profile.id,
    )

    return JsonResponse(
        {
            "order_id": order_id,
            "data": checkout.data,
            "signature": checkout.signature,
            "checkout_url": checkout.checkout_url,
            "amount": str(amount_value),
            "currency": "UAH",
            "payment_type": "credits",
            "language": profile.language,
        }
    )


# type checking of async views with require_GET is not supported by stubs
@require_GET  # type: ignore[misc]
async def payment_data(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    order_raw = request.GET.get("order_id", "")
    order_id: str = str(order_raw or "").strip()
    if not order_id:
        logger.warning("Payment data requested without order_id")
        return JsonResponse({"error": "bad_request"}, status=400)

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error

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


@require_GET  # type: ignore[misc]
async def profile_data(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error
    if profile.status == ProfileStatus.deleted:
        return JsonResponse({"error": "not_found"}, status=404)

    return JsonResponse(build_webapp_profile_payload(profile))


@csrf_exempt  # type: ignore[bad-specialization]
@require_POST  # type: ignore[misc]
async def profile_update(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error
    if profile.status == ProfileStatus.deleted:
        return JsonResponse({"error": "not_found"}, status=404)

    try:
        payload = json.loads(request.body or "{}")
    except Exception:
        logger.warning("profile_update_invalid_payload")
        return JsonResponse({"error": "bad_request"}, status=400)

    if not isinstance(payload, dict):
        return JsonResponse({"error": "bad_request"}, status=400)

    updates, error = parse_profile_updates(payload)
    if error:
        return JsonResponse(error, status=400)

    if not updates:
        return JsonResponse(build_webapp_profile_payload(profile))

    profile_instance = await call_repo(ProfileRepository.get_model_by_id, int(profile.id))
    for field_name, value in updates.items():
        setattr(profile_instance, field_name, value)
    await call_repo(profile_instance.save, update_fields=list(updates.keys()))

    ProfileRepository.invalidate_cache(profile_id=profile_instance.id, tg_id=profile_instance.tg_id)
    profile_payload = ProfileSerializer(profile_instance).data
    await Cache.profile.save_record(profile_instance.id, profile_payload)

    try:
        from core.tasks.ai_coach.maintenance import sync_profile_knowledge

        getattr(sync_profile_knowledge, "delay")(profile_instance.id, reason="profile_updated")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"profile_update_sync_failed profile_id={profile_instance.id} error={exc!s}")

    return JsonResponse(build_webapp_profile_payload(profile_instance))


@csrf_exempt  # type: ignore[bad-specialization]
@require_POST  # type: ignore[misc]
async def profile_delete(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error

    profile_instance = await call_repo(ProfileRepository.get_model_by_id, int(profile.id))
    profile_instance.status = ProfileStatus.deleted
    profile_instance.deleted_at = timezone.now()
    profile_instance.gift_credits_granted = True
    profile_instance.gender = None
    profile_instance.born_in = None
    profile_instance.weight = None
    profile_instance.height = None
    profile_instance.health_notes = None
    profile_instance.workout_experience = None
    profile_instance.workout_goals = None
    profile_instance.workout_location = None
    await call_repo(
        profile_instance.save,
        update_fields=[
            "status",
            "deleted_at",
            "gift_credits_granted",
            "gender",
            "born_in",
            "weight",
            "height",
            "health_notes",
            "workout_experience",
            "workout_goals",
            "workout_location",
        ],
    )
    ProfileRepository.invalidate_cache(profile_id=profile_instance.id, tg_id=profile_instance.tg_id)
    await Cache.profile.delete_record(profile_instance.id)

    profile_dump = build_profile_payload(profile)
    base_url, fallback_base = resolve_internal_base_url()
    proxy_payload = {
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
        headers["Content-Type"] = "application/json"
    except Exception:
        logger.exception("Failed to build internal auth headers for profile_delete")
        headers = {}

    if headers:
        resp = await post_internal_request(
            "internal/webapp/profile/deleted/",
            body,
            headers,
            base_url=base_url,
            fallback_base=fallback_base,
            timeout=internal_request_timeout(settings),
            profile_id=profile.id,
            error_label="profile_delete_dispatch_failed",
            retry_label="profile_delete_dispatch_retry",
        )
        if resp is None:
            logger.warning(f"profile_delete_dispatch_failed profile_id={profile.id} status=unreachable")
        elif resp.status_code != 200:
            logger.warning(
                "profile_delete_dispatch_failed profile_id={} status={} body={}",
                profile.id,
                resp.status_code,
                resp.text[:200],
            )

    try:
        from core.tasks.ai_coach.maintenance import cleanup_profile_knowledge

        getattr(cleanup_profile_knowledge, "delay")(profile_instance.id, reason="profile_deleted")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"profile_delete_cleanup_failed profile_id={profile_instance.id} error={exc!s}")

    return JsonResponse({"status": "ok"})


@csrf_exempt  # type: ignore[bad-specialization]
@require_POST  # type: ignore[misc]
async def profile_balance_action(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error

    profile_dump = build_profile_payload(profile)
    logger.info(f"profile_balance_action_request profile_id={profile.id}")

    base_url, fallback_base = resolve_internal_base_url()
    proxy_payload = {
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
        logger.exception("Failed to build internal auth headers for profile_balance_action")
        return JsonResponse({"error": "server_error"}, status=500)
    headers["Content-Type"] = "application/json"

    timeout = internal_request_timeout(settings)
    resp = await post_internal_request(
        "internal/webapp/profile/balance/",
        body,
        headers,
        base_url=base_url,
        fallback_base=fallback_base,
        timeout=timeout,
        profile_id=profile.id,
        error_label="profile_balance_action_failed",
        retry_label="profile_balance_action_retry",
    )
    if resp is None:
        return JsonResponse({"error": "server_error"}, status=502)

    if resp.status_code >= 400:
        logger.warning(
            (
                f"profile_balance_action_rejected profile_id={profile.id} "
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

    logger.info(f"profile_balance_action_dispatched profile_id={profile.id}")
    return JsonResponse({"status": "ok"})


@require_GET  # type: ignore[misc]
async def support_contact(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()
    return JsonResponse(build_support_contact_payload())


@csrf_exempt  # type: ignore[bad-specialization]
@require_POST  # type: ignore[misc]
async def workouts_action(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error

    try:
        payload = json.loads(request.body or "{}")
    except Exception:
        logger.warning("workouts_action_invalid_payload")
        return JsonResponse({"error": "bad_request"}, status=400)

    action = str(payload.get("action") or "")
    if action not in {"create_program", "create_subscription"}:
        return JsonResponse({"error": "bad_request"}, status=400)

    profile_dump = build_profile_payload(profile)
    logger.info(f"workouts_action_request profile_id={profile.id} action={action}")

    base_url, fallback_base = resolve_internal_base_url()
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
    resp = await post_internal_request(
        "internal/webapp/workouts/action/",
        body,
        headers,
        base_url=base_url,
        fallback_base=fallback_base,
        timeout=timeout,
        profile_id=profile.id,
        error_label="workouts_action_call_failed",
        retry_label="workouts_action_retrying_fallback",
    )
    if resp is None:
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


@require_GET  # type: ignore[misc]
async def workout_plan_options(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error

    pricing = workout_plan_pricing()
    return JsonResponse(build_workout_plan_options_payload(pricing))


@require_GET  # type: ignore[misc]
async def diet_plan_options(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error

    return JsonResponse({"price": int(settings.DIET_PLAN_PRICE)})


@require_GET  # type: ignore[misc]
async def diet_plans_list(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error

    try:
        plans = await call_repo(DietPlanRepository.get_all, int(profile.id))
    except Exception:
        logger.exception(f"Failed to fetch diet plans profile_id={profile.id}")
        return JsonResponse({"error": "server_error"}, status=500)

    items = [{"id": int(plan.id), "created_at": parse_timestamp(getattr(plan, "created_at", None))} for plan in plans]
    return JsonResponse({"diets": items, "language": profile.language})


@require_GET  # type: ignore[misc]
async def diet_plan_data(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error

    diet_id, id_error = _parse_diet_id(request)
    if id_error:
        return id_error

    try:
        if diet_id is not None:
            plan = await call_repo(DietPlanRepository.get_by_id, int(profile.id), diet_id)
        else:
            plans = await call_repo(DietPlanRepository.get_all, int(profile.id))
            plan = plans[0] if plans else None
    except Exception:
        logger.exception(f"Failed to fetch diet plan profile_id={profile.id} diet_id={diet_id}")
        return JsonResponse({"error": "server_error"}, status=500)

    if plan is None:
        return JsonResponse({"error": "not_found"}, status=404)

    return JsonResponse(
        {
            "id": int(plan.id),
            "created_at": parse_timestamp(getattr(plan, "created_at", None)),
            "plan": plan.plan,
            "language": profile.language,
        }
    )


@csrf_exempt  # type: ignore[bad-specialization]
@require_POST  # type: ignore[misc]
async def diet_plan_create(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error

    if not await APIService.ai_coach.health():
        logger.warning(f"diet_plan_create_aborted_unhealthy profile_id={profile.id}")
        return JsonResponse({"error": "service_unavailable"}, status=503)

    required = int(settings.DIET_PLAN_PRICE)
    credits = int(getattr(profile, "credits", 0) or 0)
    if credits < required:
        return JsonResponse({"error": "not_enough_credits"}, status=400)

    if profile.diet_products is None:
        return JsonResponse({"error": "diet_preferences_required"}, status=400)

    diet_allergies = str(profile.diet_allergies or "").strip() or None
    diet_products = list(profile.diet_products or [])
    language = str(getattr(profile, "language", settings.DEFAULT_LANG) or settings.DEFAULT_LANG)

    new_credits = max(0, credits - required)
    await call_repo(Profile.objects.filter(id=profile.id).update, credits=new_credits)
    await call_repo(ProfileRepository.invalidate_cache, profile.id, getattr(profile, "tg_id", None))
    await Cache.profile.update_record(profile.id, {"credits": new_credits})

    task_id = enqueue_diet_plan_generation(
        profile_id=profile.id,
        language=language,
        diet_allergies=diet_allergies,
        diet_products=diet_products,
        cost=required,
    )
    if task_id is None:
        return JsonResponse({"error": "server_error"}, status=500)

    return JsonResponse({"status": "ok", "task_id": task_id})


@csrf_exempt  # type: ignore[bad-specialization]
@require_POST  # type: ignore[misc]
async def diet_plan_save_internal(request: HttpRequest) -> JsonResponse:
    body = request.body or b""
    ok, error_response = validate_internal_hmac(request, body)
    if not ok:
        return error_response or JsonResponse({"detail": "Unauthorized"}, status=403)

    try:
        payload_raw = json.loads(body.decode("utf-8") or "{}")
    except Exception:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    try:
        payload = DietPlanSavePayload.model_validate(payload_raw)
    except ValidationError as exc:
        return JsonResponse({"detail": exc.errors()}, status=400)

    profile_id = int(payload.profile_id)
    request_id = str(payload.request_id)

    profile_exists = await call_repo(Profile.objects.filter(id=profile_id).exists)
    if not profile_exists:
        return JsonResponse({"detail": "profile_not_found"}, status=404)

    existing = await call_repo(DietPlanRepository.get_by_request_id, request_id)
    if existing is not None:
        return JsonResponse({"status": "ok", "diet_id": int(existing.id), "created": False})

    plan_payload = payload.plan.model_dump(mode="json")
    created = await call_repo(
        DietPlanRepository.create,
        profile_id=profile_id,
        request_id=request_id,
        plan=plan_payload,
    )
    return JsonResponse({"status": "ok", "diet_id": int(created.id), "created": True})


@csrf_exempt  # type: ignore[bad-specialization]
@require_POST  # type: ignore[misc]
async def workout_plan_create(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error

    if not await APIService.ai_coach.health():
        logger.warning(f"workout_plan_create_aborted_unhealthy profile_id={profile.id}")
        return JsonResponse({"error": "service_unavailable"}, status=503)

    try:
        payload_raw = json.loads(request.body or "{}")
    except Exception:
        logger.warning("workout_plan_create_invalid_payload")
        return JsonResponse({"error": "bad_request"}, status=400)

    try:
        payload = WorkoutPlanRequest.model_validate(payload_raw)
    except ValidationError as exc:
        logger.warning(f"workout_plan_create_invalid_schema error={exc!s}")
        return JsonResponse({"error": "bad_request"}, status=400)

    pricing = workout_plan_pricing()
    required = resolve_workout_plan_required(pricing, payload, profile_id=profile.id)
    if required is None:
        return JsonResponse({"error": "bad_request"}, status=400)

    credits = int(getattr(profile, "credits", 0) or 0)
    if credits < required:
        return JsonResponse({"error": "not_enough_credits"}, status=400)

    workout_location = resolve_workout_location(profile)
    if workout_location is None:
        logger.warning(f"workout_plan_location_missing profile_id={profile.id}")
        return JsonResponse({"error": "bad_request"}, status=400)

    split_number = int(payload.split_number)
    wishes = payload.wishes
    language = str(getattr(profile, "language", settings.DEFAULT_LANG) or settings.DEFAULT_LANG)
    subscription_id: int | None = None
    previous_subscription_id: int | None = None

    if payload.plan_type is WorkoutPlanType.SUBSCRIPTION:
        subscription_id, previous_subscription_id = await create_subscription_record(
            profile=profile,
            payload=payload,
            required=required,
            workout_location=workout_location,
            split_number=split_number,
            wishes=wishes,
        )
        if not subscription_id:
            logger.error(f"workout_plan_subscription_create_failed profile_id={profile.id}")
            return JsonResponse({"error": "server_error"}, status=500)

    new_credits = max(0, credits - required)
    await call_repo(Profile.objects.filter(id=profile.id).update, credits=new_credits)
    await call_repo(ProfileRepository.invalidate_cache, profile.id, getattr(profile, "tg_id", None))
    await Cache.profile.update_record(profile.id, {"credits": new_credits})

    if payload.plan_type is WorkoutPlanType.SUBSCRIPTION and subscription_id is not None:
        await Cache.workout.update_subscription(
            profile.id,
            {
                "id": subscription_id,
                "enabled": False,
                "period": payload.period.value if payload.period else None,
                "price": required,
                "workout_location": workout_location.value,
                "wishes": wishes,
                "split_number": split_number,
            },
        )

    task_id = enqueue_workout_plan_generation(
        profile_id=profile.id,
        language=language,
        plan_type=payload.plan_type,
        workout_location=workout_location,
        wishes=wishes,
        split_number=split_number,
        period=payload.period,
        previous_subscription_id=previous_subscription_id,
    )
    if not task_id:
        return JsonResponse({"error": "server_error"}, status=500)

    return JsonResponse({"status": "ok", "subscription_id": subscription_id, "task_id": task_id})


@csrf_exempt  # type: ignore[bad-specialization]
@require_POST  # type: ignore[misc]
async def weekly_survey_submit(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error

    try:
        payload_raw = json.loads(request.body or "{}")
    except Exception:
        logger.warning("weekly_survey_invalid_payload")
        return JsonResponse({"error": "bad_request"}, status=400)

    try:
        payload = WeeklySurveyPayload.model_validate(payload_raw)
    except ValidationError as exc:
        logger.warning(f"weekly_survey_invalid_schema error={exc!s}")
        return JsonResponse({"error": "bad_request"}, status=400)

    subscription_id = payload.subscription_id
    subscription = cast(
        Subscription | None,
        await call_repo(
            lambda pid: SubscriptionRepository.base_qs()
            .filter(profile_id=pid, id=subscription_id, enabled=True)
            .first(),
            int(getattr(profile, "id", 0)),
        ),
    )
    if subscription is None:
        return JsonResponse({"error": "not_found"}, status=404)

    exercises_by_day = getattr(subscription, "exercises", None)
    if not isinstance(exercises_by_day, list):
        return JsonResponse({"error": "server_error"}, status=500)

    sets_updated = False
    for day in payload.days:
        for exercise in day.exercises:
            if not exercise.sets_detail:
                continue
            entry = resolve_exercise_entry(exercises_by_day, exercise.id)
            if entry is None:
                continue
            sets_payload: list[ExerciseSetPayload] = [
                {"reps": int(item.reps), "weight": float(item.weight)} for item in exercise.sets_detail
            ]
            if not sets_payload:
                continue
            weight_unit = next((item.weight_unit for item in exercise.sets_detail if item.weight_unit), None)
            apply_sets_update(
                entry,
                {
                    "weight_unit": weight_unit,
                    "sets": sets_payload,
                },
            )
            sets_updated = True

    if sets_updated:
        await call_repo(SubscriptionRepository.update_exercises, profile.id, exercises_by_day, subscription)
        await Cache.workout.update_subscription(profile.id, {"exercises": exercises_by_day})

    plan_age_weeks = resolve_plan_age_weeks(getattr(subscription, "updated_at", None))
    context = SurveyFeedbackContext(
        workout_goals=getattr(profile, "workout_goals", None),
        workout_experience=getattr(profile, "workout_experience", None),
        plan_age_weeks=plan_age_weeks,
    )
    feedback = build_weekly_survey_feedback(payload, context=context)

    workout_location_value = getattr(subscription, "workout_location", None) or getattr(
        profile, "workout_location", None
    )
    workout_location: WorkoutLocation | None = None
    if workout_location_value:
        try:
            workout_location = WorkoutLocation(str(workout_location_value))
        except ValueError:
            workout_location = None

    request_id = uuid4().hex
    queued = enqueue_subscription_update(
        profile_id=profile.id,
        language=profile.language or settings.DEFAULT_LANG,
        feedback=feedback,
        workout_location=workout_location,
        request_id=request_id,
    )
    if not queued:
        return JsonResponse({"error": "service_unavailable"}, status=503)

    base_url, fallback_base = resolve_internal_base_url()
    logger.debug(f"weekly_survey_internal_base profile_id={profile.id} base_url={base_url}")

    proxy_payload = {
        "profile_id": profile.id,
        "telegram_id": profile.tg_id,
        "profile": build_profile_payload(profile),
    }
    body = json.dumps(proxy_payload).encode("utf-8")
    try:
        headers = build_internal_hmac_auth_headers(
            key_id=settings.INTERNAL_KEY_ID,
            secret_key=settings.INTERNAL_API_KEY,
            body=body,
        )
    except Exception:
        logger.exception("Failed to build internal auth headers for weekly_survey_submit")
        headers = None

    if headers:
        headers["Content-Type"] = "application/json"
        timeout = internal_request_timeout(settings)
        resp = await post_internal_request(
            "internal/webapp/weekly-survey/submitted/",
            body,
            headers,
            base_url=base_url,
            fallback_base=fallback_base,
            timeout=timeout,
            profile_id=profile.id,
            error_label="weekly_survey_notify_failed",
            retry_label="weekly_survey_notify_retry",
        )
        if resp is not None and resp.status_code >= 400:
            logger.warning(
                "weekly_survey_notify_rejected "
                f"profile_id={profile.id} status={resp.status_code} body={resp.text[:200]}"
            )

    subscription_log_id = getattr(subscription, "id", None)
    logger.info(
        f"weekly_survey_enqueued profile_id={profile.id} request_id={request_id} subscription_id={subscription_log_id}"
    )
    return JsonResponse({"status": "ok", "request_id": request_id})


@csrf_exempt  # type: ignore[bad-specialization]
@require_POST  # type: ignore[misc]
async def update_exercise_sets(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error

    try:
        payload_raw = json.loads(request.body or "{}")
    except Exception:
        logger.warning("update_exercise_sets_invalid_payload")
        return JsonResponse({"error": "bad_request"}, status=400)

    exercise_id_raw = payload_raw.get("exercise_id")
    program_id_raw = payload_raw.get("program_id")
    sets_raw = payload_raw.get("sets")
    weight_unit_raw = payload_raw.get("weight_unit")

    if not exercise_id_raw or not isinstance(exercise_id_raw, str):
        return JsonResponse({"error": "bad_request"}, status=400)
    try:
        program_id = int(program_id_raw)
    except (TypeError, ValueError):
        program_id = 0
    if not program_id:
        return JsonResponse({"error": "bad_request"}, status=400)
    sets_payload = parse_sets_payload(sets_raw)
    if not sets_payload:
        return JsonResponse({"error": "bad_request"}, status=400)

    weight_unit = str(weight_unit_raw) if weight_unit_raw is not None else None
    payload: UpdateExercisePayload = {
        "program_id": program_id,
        "exercise_id": exercise_id_raw,
        "weight_unit": weight_unit,
        "sets": sets_payload,
    }

    program = await call_repo(ProgramRepository.get_by_id, profile.id, program_id)
    if program is None:
        return JsonResponse({"error": "not_found"}, status=404)

    exercises_by_day = getattr(program, "exercises_by_day", None)
    if not isinstance(exercises_by_day, list):
        return JsonResponse({"error": "server_error"}, status=500)

    entry = resolve_exercise_entry(exercises_by_day, exercise_id_raw)
    if entry is None:
        return JsonResponse({"error": "not_found"}, status=404)
    if is_aux_exercise_entry(entry):
        return JsonResponse({"error": "bad_request"}, status=400)

    apply_sets_update(entry, payload)

    await call_repo(ProgramRepository.create_or_update, profile.id, exercises_by_day, instance=program)
    logger.info(f"exercise_sets_updated profile_id={profile.id} program_id={program_id} exercise_id={exercise_id_raw}")
    return JsonResponse({"status": "ok"})


@csrf_exempt  # type: ignore[bad-specialization]
@require_POST  # type: ignore[misc]
async def update_subscription_exercise_sets(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error

    try:
        payload_raw = json.loads(request.body or "{}")
    except Exception:
        logger.warning("update_subscription_exercise_sets_invalid_payload")
        return JsonResponse({"error": "bad_request"}, status=400)

    exercise_id_raw = payload_raw.get("exercise_id")
    subscription_id_raw = payload_raw.get("subscription_id")
    sets_raw = payload_raw.get("sets")
    weight_unit_raw = payload_raw.get("weight_unit")

    if not exercise_id_raw or not isinstance(exercise_id_raw, str):
        return JsonResponse({"error": "bad_request"}, status=400)
    try:
        subscription_id = int(subscription_id_raw)
    except (TypeError, ValueError):
        subscription_id = 0
    if not subscription_id:
        return JsonResponse({"error": "bad_request"}, status=400)
    sets_payload = parse_sets_payload(sets_raw)
    if not sets_payload:
        return JsonResponse({"error": "bad_request"}, status=400)

    weight_unit = str(weight_unit_raw) if weight_unit_raw is not None else None
    payload: UpdateSubscriptionExercisePayload = {
        "subscription_id": subscription_id,
        "exercise_id": exercise_id_raw,
        "weight_unit": weight_unit,
        "sets": sets_payload,
    }

    subscription = cast(
        Subscription | None,
        await call_repo(
            lambda pid: SubscriptionRepository.base_qs()
            .filter(profile_id=pid, id=subscription_id, enabled=True)
            .first(),
            profile.id,
        ),
    )
    if subscription is None:
        return JsonResponse({"error": "not_found"}, status=404)

    exercises_by_day = getattr(subscription, "exercises", None)
    if not isinstance(exercises_by_day, list):
        return JsonResponse({"error": "server_error"}, status=500)

    entry = resolve_exercise_entry(exercises_by_day, exercise_id_raw)
    if entry is None:
        return JsonResponse({"error": "not_found"}, status=404)
    if is_aux_exercise_entry(entry):
        return JsonResponse({"error": "bad_request"}, status=400)

    apply_sets_update(entry, payload)

    await call_repo(SubscriptionRepository.update_exercises, profile.id, exercises_by_day, subscription)
    await Cache.workout.update_subscription(profile.id, {"exercises": exercises_by_day})
    logger.info(
        "subscription_exercise_sets_updated "
        f"profile_id={profile.id} subscription_id={subscription_id} exercise_id={exercise_id_raw}"
    )
    return JsonResponse({"status": "ok"})


@csrf_exempt  # type: ignore[bad-specialization]
@require_POST  # type: ignore[misc]
async def replace_exercise(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error

    try:
        payload_raw = json.loads(request.body or "{}")
    except Exception:
        logger.warning("replace_exercise_invalid_payload")
        return JsonResponse({"error": "bad_request"}, status=400)

    exercise_id_raw = payload_raw.get("exercise_id")
    program_id_raw = payload_raw.get("program_id")
    use_credits_raw = payload_raw.get("use_credits")
    use_credits = parse_bool(use_credits_raw)
    if not exercise_id_raw or not isinstance(exercise_id_raw, str):
        return JsonResponse({"error": "bad_request"}, status=400)
    try:
        program_id = int(program_id_raw)
    except (TypeError, ValueError):
        program_id = 0
    if not program_id:
        return JsonResponse({"error": "bad_request"}, status=400)

    program = await call_repo(ProgramRepository.get_by_id, profile.id, program_id)
    if program is None:
        return JsonResponse({"error": "not_found"}, status=404)
    exercises_by_day = getattr(program, "exercises_by_day", None)
    if not isinstance(exercises_by_day, list):
        return JsonResponse({"error": "server_error"}, status=500)
    entry = resolve_exercise_entry(exercises_by_day, exercise_id_raw)
    if is_aux_exercise_entry(entry):
        return JsonResponse({"error": "bad_request"}, status=400)

    free_available = consume_program_replace_limit(program_id)
    if not free_available:
        required = int(settings.EXERCISE_REPLACE_PRICE)
        credits = int(getattr(profile, "credits", 0) or 0)
        if not use_credits:
            return JsonResponse(
                {
                    "error": "payment_required",
                    "price": required,
                    "balance": credits,
                    "can_afford": credits >= required,
                },
                status=402,
            )
        if not atomic_debit_credits(profile.id, required):
            refreshed_credits = int(
                await call_repo(Profile.objects.filter(id=profile.id).values_list("credits", flat=True).first)
                or credits
            )
            return JsonResponse(
                {
                    "error": "payment_required",
                    "price": required,
                    "balance": refreshed_credits,
                    "can_afford": refreshed_credits >= required,
                },
                status=402,
            )
        await call_repo(ProfileRepository.invalidate_cache, profile.id, getattr(profile, "tg_id", None))
        refreshed_credits = int(
            await call_repo(Profile.objects.filter(id=profile.id).values_list("credits", flat=True).first) or 0
        )
        await Cache.profile.update_record(profile.id, {"credits": refreshed_credits})
        logger.info(
            "exercise_replace_charged profile_id={} program_id={} credits_spent={} credits_left={}",
            profile.id,
            program_id,
            required,
            refreshed_credits,
        )

    task_id = enqueue_exercise_replace_task(profile.id, program_id, exercise_id_raw)
    if not task_id:
        return JsonResponse({"error": "server_error"}, status=500)
    cache.set(
        f"exercise_replace:{task_id}",
        {"status": "queued", "profile_id": profile.id},
        timeout=settings.AI_COACH_TIMEOUT,
    )
    return JsonResponse({"task_id": task_id})


@csrf_exempt  # type: ignore[bad-specialization]
@require_POST  # type: ignore[misc]
async def replace_subscription_exercise(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error

    try:
        payload_raw = json.loads(request.body or "{}")
    except Exception:
        logger.warning("replace_subscription_exercise_invalid_payload")
        return JsonResponse({"error": "bad_request"}, status=400)

    exercise_id_raw = payload_raw.get("exercise_id")
    subscription_id_raw = payload_raw.get("subscription_id")
    use_credits_raw = payload_raw.get("use_credits")
    use_credits = parse_bool(use_credits_raw)
    if not exercise_id_raw or not isinstance(exercise_id_raw, str):
        return JsonResponse({"error": "bad_request"}, status=400)
    try:
        subscription_id = int(subscription_id_raw)
    except (TypeError, ValueError):
        subscription_id = 0
    if not subscription_id:
        return JsonResponse({"error": "bad_request"}, status=400)

    subscription = cast(
        Subscription | None,
        await call_repo(
            lambda pid: SubscriptionRepository.base_qs()
            .filter(profile_id=pid, id=subscription_id, enabled=True)
            .first(),
            profile.id,
        ),
    )
    if subscription is None:
        return JsonResponse({"error": "not_found"}, status=404)

    exercises_by_day = getattr(subscription, "exercises", None)
    if not isinstance(exercises_by_day, list):
        return JsonResponse({"error": "server_error"}, status=500)
    entry = resolve_exercise_entry(exercises_by_day, exercise_id_raw)
    if is_aux_exercise_entry(entry):
        return JsonResponse({"error": "bad_request"}, status=400)

    free_available = consume_subscription_replace_limit(subscription.id, period=str(subscription.period))
    if not free_available:
        required = int(settings.EXERCISE_REPLACE_PRICE)
        credits = int(getattr(profile, "credits", 0) or 0)
        if not use_credits:
            return JsonResponse(
                {
                    "error": "payment_required",
                    "price": required,
                    "balance": credits,
                    "can_afford": credits >= required,
                },
                status=402,
            )
        if not atomic_debit_credits(profile.id, required):
            refreshed_credits = int(
                await call_repo(Profile.objects.filter(id=profile.id).values_list("credits", flat=True).first)
                or credits
            )
            return JsonResponse(
                {
                    "error": "payment_required",
                    "price": required,
                    "balance": refreshed_credits,
                    "can_afford": refreshed_credits >= required,
                },
                status=402,
            )
        await call_repo(ProfileRepository.invalidate_cache, profile.id, getattr(profile, "tg_id", None))
        refreshed_credits = int(
            await call_repo(Profile.objects.filter(id=profile.id).values_list("credits", flat=True).first) or 0
        )
        await Cache.profile.update_record(profile.id, {"credits": refreshed_credits})
        logger.info(
            "exercise_replace_charged profile_id={} subscription_id={} credits_spent={} credits_left={}",
            profile.id,
            subscription.id,
            required,
            refreshed_credits,
        )

    task_id = enqueue_subscription_exercise_replace_task(profile.id, subscription.id, exercise_id_raw)
    if not task_id:
        return JsonResponse({"error": "server_error"}, status=500)
    cache.set(
        f"exercise_replace:{task_id}",
        {"status": "queued", "profile_id": profile.id},
        timeout=settings.AI_COACH_TIMEOUT,
    )
    return JsonResponse({"task_id": task_id})


async def _replace_exercise_status(request: HttpRequest) -> JsonResponse:
    await ensure_container_ready()

    profile_or_error = await resolve_profile(request)
    if isinstance(profile_or_error, JsonResponse):
        return profile_or_error
    profile = profile_or_error

    task_id_raw = request.GET.get("task_id")
    if not task_id_raw:
        return JsonResponse({"error": "bad_request"}, status=400)

    cache_key = f"exercise_replace:{task_id_raw}"
    cached = cache.get(cache_key)
    if not isinstance(cached, dict):
        return JsonResponse({"error": "not_found"}, status=404)
    if cached.get("profile_id") != profile.id:
        return JsonResponse({"error": "not_found"}, status=404)

    return JsonResponse({"status": cached.get("status"), "error": cached.get("error")})


@require_GET  # type: ignore[misc]
async def replace_exercise_status(request: HttpRequest) -> JsonResponse:
    return await _replace_exercise_status(request)


@require_GET  # type: ignore[misc]
async def replace_subscription_exercise_status(request: HttpRequest) -> JsonResponse:
    return await _replace_exercise_status(request)


def index(request: HttpRequest) -> HttpResponse:
    logger.info(f"Webapp hit: {request.method} {request.get_full_path()}")
    return render(
        request,
        "webapp/index.html",
        {
            "static_version": STATIC_VERSION,
        },
    )


def ping(request: HttpRequest) -> HttpResponse:
    logger.info(f"Webapp ping: {request.method} {request.get_full_path()}")
    return HttpResponse("ok")


@require_GET  # type: ignore[misc]
async def generation_status(request: HttpRequest) -> JsonResponse:
    task_id = request.GET.get("task_id")
    if not task_id:
        return JsonResponse({"error": "bad_request"}, status=400)

    status_data = cache.get(f"generation_status:{task_id}")
    if not isinstance(status_data, dict):
        return JsonResponse({"status": "unknown", "progress": 0})

    return JsonResponse(status_data)
