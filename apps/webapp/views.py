import json
from datetime import datetime
from uuid import uuid4
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, cast

import httpx
from django.http import HttpRequest, HttpResponse, JsonResponse
from google.api_core.exceptions import NotFound as GCSNotFound
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from loguru import logger
from pydantic import ValidationError
from rest_framework.exceptions import NotFound

from apps.payments.repos import PaymentRepository
from apps.workout_plans.models import Program as ProgramModel
from apps.workout_plans.repos import ProgramRepository, SubscriptionRepository
from apps.webapp.weekly_survey import (
    WeeklySurveyPayload,
    SurveyFeedbackContext,
    build_weekly_survey_feedback,
    enqueue_subscription_update,
    resolve_plan_age_weeks,
)
from config.app_settings import settings
from core.internal_http import build_internal_hmac_auth_headers, internal_request_timeout
from core.cache import Cache
from core.enums import WorkoutLocation
from core.schemas import Program as ProgramSchema, Subscription
from django.core.cache import cache
from core.ai_coach.exercise_catalog import load_exercise_catalog
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
    resolve_exercise_entry,
)
from .utils import STATIC_VERSION, transform_days

from .utils import (
    authenticate,
    build_payment_gateway,
    call_repo,
    ensure_container_ready,
    parse_program_id,
    parse_subscription_id,
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
        auth_ctx = await authenticate(request, log_request=False)
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

    subscription_id, id_error = parse_subscription_id(request)
    if id_error:
        return id_error

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
    days = transform_days(exercises)
    response: dict[str, object] = {"days": days, "language": profile.language, "program": days}
    if subscription_id is not None:
        response["id"] = str(subscription_id)
    return JsonResponse(response)


@require_GET  # type: ignore[misc]
async def subscription_status(request: HttpRequest) -> JsonResponse:
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


@csrf_exempt  # type: ignore[bad-specialization]
@require_POST  # type: ignore[misc]
async def weekly_survey_submit(request: HttpRequest) -> JsonResponse:
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

    raw_base_url = (settings.BOT_INTERNAL_URL or "").rstrip("/")
    fallback_base = f"http://{settings.BOT_INTERNAL_HOST}:{settings.BOT_INTERNAL_PORT}"
    base_url = raw_base_url or fallback_base
    logger.debug(f"weekly_survey_internal_base profile_id={profile.id} base_url={base_url}")

    proxy_payload = {
        "profile_id": profile.id,
        "telegram_id": profile.tg_id,
        "profile": {
            "id": profile.id,
            "tg_id": profile.tg_id,
            "language": profile.language or settings.DEFAULT_LANG,
            "status": profile.status,
        },
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

        async def _post(target_url: str) -> httpx.Response:
            async with httpx.AsyncClient(timeout=timeout) as client:
                return await client.post(target_url, content=body, headers=headers)

        primary_url = f"{base_url}/internal/webapp/weekly-survey/submitted/"
        try:
            resp = await _post(primary_url)
            if resp.status_code >= 400:
                logger.warning(
                    "weekly_survey_notify_rejected "
                    f"profile_id={profile.id} status={resp.status_code} body={resp.text[:200]}"
                )
        except httpx.HTTPError as exc:
            logger.error(f"weekly_survey_notify_failed profile_id={profile.id} base_url={base_url} err={exc}")
            if base_url != fallback_base:
                fallback_url = f"{fallback_base}/internal/webapp/weekly-survey/submitted/"
                logger.info(f"weekly_survey_notify_retry profile_id={profile.id} fallback={fallback_base}")
                try:
                    resp = await _post(fallback_url)
                    if resp.status_code >= 400:
                        logger.warning(
                            "weekly_survey_notify_rejected "
                            f"profile_id={profile.id} status={resp.status_code} body={resp.text[:200]}"
                        )
                except httpx.HTTPError as exc2:
                    logger.error(
                        f"weekly_survey_notify_failed profile_id={profile.id} fallback={fallback_base} err={exc2}"
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
    if not isinstance(sets_raw, list) or not sets_raw:
        return JsonResponse({"error": "bad_request"}, status=400)

    sets_payload: list[ExerciseSetPayload] = []
    for entry in sets_raw:
        if not isinstance(entry, dict):
            return JsonResponse({"error": "bad_request"}, status=400)
        reps_raw = entry.get("reps")
        weight_raw = entry.get("weight")
        if not isinstance(reps_raw, (int, str)):
            return JsonResponse({"error": "bad_request"}, status=400)
        if not isinstance(weight_raw, (int, float, str)):
            return JsonResponse({"error": "bad_request"}, status=400)
        try:
            reps_value = int(str(reps_raw))
            weight_value = float(str(weight_raw))
        except (TypeError, ValueError):
            return JsonResponse({"error": "bad_request"}, status=400)
        if reps_value < 1 or weight_value < 0:
            return JsonResponse({"error": "bad_request"}, status=400)
        sets_payload.append({"reps": reps_value, "weight": weight_value})

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

    apply_sets_update(entry, payload)

    await call_repo(ProgramRepository.create_or_update, profile.id, exercises_by_day, instance=program)
    logger.info(f"exercise_sets_updated profile_id={profile.id} program_id={program_id} exercise_id={exercise_id_raw}")
    return JsonResponse({"status": "ok"})


@csrf_exempt  # type: ignore[bad-specialization]
@require_POST  # type: ignore[misc]
async def update_subscription_exercise_sets(request: HttpRequest) -> JsonResponse:
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
    if not isinstance(sets_raw, list) or not sets_raw:
        return JsonResponse({"error": "bad_request"}, status=400)

    sets_payload: list[ExerciseSetPayload] = []
    for entry in sets_raw:
        if not isinstance(entry, dict):
            return JsonResponse({"error": "bad_request"}, status=400)
        reps_raw = entry.get("reps")
        weight_raw = entry.get("weight")
        if not isinstance(reps_raw, (int, str)):
            return JsonResponse({"error": "bad_request"}, status=400)
        if not isinstance(weight_raw, (int, float, str)):
            return JsonResponse({"error": "bad_request"}, status=400)
        try:
            reps_value = int(str(reps_raw))
            weight_value = float(str(weight_raw))
        except (TypeError, ValueError):
            return JsonResponse({"error": "bad_request"}, status=400)
        if reps_value < 1 or weight_value < 0:
            return JsonResponse({"error": "bad_request"}, status=400)
        sets_payload.append({"reps": reps_value, "weight": weight_value})

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
        payload_raw = json.loads(request.body or "{}")
    except Exception:
        logger.warning("replace_exercise_invalid_payload")
        return JsonResponse({"error": "bad_request"}, status=400)

    exercise_id_raw = payload_raw.get("exercise_id")
    program_id_raw = payload_raw.get("program_id")
    if not exercise_id_raw or not isinstance(exercise_id_raw, str):
        return JsonResponse({"error": "bad_request"}, status=400)
    try:
        program_id = int(program_id_raw)
    except (TypeError, ValueError):
        program_id = 0
    if not program_id:
        return JsonResponse({"error": "bad_request"}, status=400)

    if not consume_program_replace_limit(program_id):
        logger.info(f"exercise_replace_limit_reached profile_id={profile.id} program_id={program_id}")
        return JsonResponse({"error": "limit_reached"}, status=429)

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
        payload_raw = json.loads(request.body or "{}")
    except Exception:
        logger.warning("replace_subscription_exercise_invalid_payload")
        return JsonResponse({"error": "bad_request"}, status=400)

    exercise_id_raw = payload_raw.get("exercise_id")
    subscription_id_raw = payload_raw.get("subscription_id")
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

    if not consume_subscription_replace_limit(subscription.id, period=str(subscription.period)):
        logger.info(
            f"exercise_replace_limit_reached profile_id={profile.id} subscription_id={subscription.id} "
            f"period={subscription.period}"
        )
        return JsonResponse({"error": "limit_reached"}, status=429)

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
    return render(request, "webapp/index.html", {"static_version": STATIC_VERSION})


def ping(request: HttpRequest) -> HttpResponse:
    logger.info(f"Webapp ping: {request.method} {request.get_full_path()}")
    return HttpResponse("ok")
