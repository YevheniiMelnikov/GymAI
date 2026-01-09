from typing import cast
from uuid import uuid4

from celery import chain
from celery.result import AsyncResult
from loguru import logger
from pydantic import ValidationError

from core.ai_coach import AiDietPlanPayload
from core.tasks.ai_coach import generate_ai_diet_plan, handle_ai_diet_failure, notify_ai_diet_ready_task
from django.core.cache import cache
from config.app_settings import settings


def enqueue_diet_plan_generation(
    *,
    profile_id: int,
    language: str,
    diet_allergies: str | None,
    diet_products: list[str],
    cost: int,
) -> str | None:
    request_id = uuid4().hex
    allergy_note = diet_allergies or "none"
    products_note = ", ".join(diet_products) if diet_products else "not specified"
    prompt = f"Create a 1-day diet plan. Allergies: {allergy_note}. Allowed products: {products_note}."

    try:
        payload_model = AiDietPlanPayload(
            profile_id=profile_id,
            language=language,
            request_id=request_id,
            cost=cost,
            prompt=prompt,
            diet_allergies=diet_allergies,
            diet_products=diet_products,
        )
    except ValidationError as exc:
        logger.error(f"webapp_diet_invalid_payload profile_id={profile_id} request_id={request_id} error={exc!s}")
        return None

    payload = payload_model.model_dump(mode="json")
    headers = {
        "request_id": request_id,
        "profile_id": profile_id,
        "action": "diet",
    }
    options = {"queue": "ai_coach", "routing_key": "ai_coach", "headers": headers}

    logger.info(
        "webapp_diet_generation_start request_id={} profile_id={} diet_products={}",
        request_id,
        profile_id,
        len(diet_products),
    )

    try:
        diet_sig = generate_ai_diet_plan.s(payload).set(**options)  # pyrefly: ignore[not-callable]
        notify_sig = notify_ai_diet_ready_task.s().set(  # pyrefly: ignore[not-callable]
            queue="ai_coach",
            routing_key="ai_coach",
            headers=headers,
        )
        failure_sig = handle_ai_diet_failure.s(payload).set(  # pyrefly: ignore[not-callable]
            queue="ai_coach",
            routing_key="ai_coach",
        )
        async_result = cast(AsyncResult, chain(diet_sig, notify_sig).apply_async(link_error=[failure_sig]))
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "webapp_diet_dispatch_failed profile_id={} request_id={} error={}",
            profile_id,
            request_id,
            exc,
        )
        return None

    task_id = cast(str | None, getattr(async_result, "id", None))
    if task_id is None:
        logger.error(f"webapp_diet_missing_task_id profile_id={profile_id} request_id={request_id}")
        return None

    cache.set(
        f"generation_status:{request_id}",
        {"status": "queued", "progress": 5, "stage": "queued"},
        timeout=settings.AI_COACH_TIMEOUT,
    )

    logger.debug(
        "webapp_diet_dispatch_success request_id={} profile_id={} task_id={}",
        request_id,
        profile_id,
        task_id,
    )
    return request_id
