from typing import cast

from celery import chain
from celery.result import AsyncResult
from loguru import logger
from pydantic import ValidationError

from config.app_settings import settings
from core.ai_coach import AiDietPlanPayload
from core.schemas import Profile
from core.tasks.ai_coach import generate_ai_diet_plan, notify_ai_diet_ready_task, handle_ai_diet_failure


async def enqueue_diet_plan_generation(
    *,
    profile: Profile,
    diet_allergies: str | None,
    diet_products: list[str],
    request_id: str,
    cost: int,
) -> bool:
    profile_id = profile.id
    if profile_id <= 0:
        logger.error(f"event=ai_diet_invalid_profile request_id={request_id} profile_id={profile_id}")
        return False

    language = str(profile.language or settings.DEFAULT_LANG)
    allergy_note = diet_allergies or "none"
    products_note = ", ".join(diet_products) if diet_products else "not specified"
    prompt = f"Create a 1-day diet plan. Allergies: {allergy_note}. Allowed products: {products_note}."
    payload_model = _build_ai_diet_payload(
        profile_id=profile_id,
        language=language,
        prompt=prompt,
        request_id=request_id,
        cost=cost,
        diet_allergies=diet_allergies,
        diet_products=diet_products,
    )
    if payload_model is None:
        return False

    task_id = _dispatch_ai_diet_task(
        payload_model=payload_model,
        request_id=request_id,
        profile_id=profile_id,
    )
    return task_id is not None


def _build_ai_diet_payload(
    *,
    profile_id: int,
    language: str,
    prompt: str,
    request_id: str,
    cost: int,
    diet_allergies: str | None,
    diet_products: list[str],
) -> AiDietPlanPayload | None:
    try:
        return AiDietPlanPayload(
            profile_id=profile_id,
            language=language,
            request_id=request_id,
            cost=cost,
            prompt=prompt,
            diet_allergies=diet_allergies,
            diet_products=diet_products,
        )
    except ValidationError as exc:
        logger.error(f"event=ai_diet_invalid_payload request_id={request_id} profile_id={profile_id} error={exc!s}")
        return None


def _dispatch_ai_diet_task(
    *,
    payload_model: AiDietPlanPayload,
    request_id: str,
    profile_id: int,
) -> str | None:
    payload = payload_model.model_dump(mode="json")
    headers = {
        "request_id": request_id,
        "profile_id": profile_id,
        "action": "diet",
    }
    options = {"queue": "ai_coach", "routing_key": "ai_coach", "headers": headers}

    diet_sig = generate_ai_diet_plan.s(payload).set(**options)  # pyrefly: ignore[not-callable]
    notify_sig = notify_ai_diet_ready_task.s().set(  # pyrefly: ignore[not-callable]
        queue="ai_coach", routing_key="ai_coach", headers=headers
    )
    failure_sig = handle_ai_diet_failure.s(payload).set(  # pyrefly: ignore[not-callable]
        queue="ai_coach", routing_key="ai_coach"
    )

    try:
        async_result = cast(AsyncResult, chain(diet_sig, notify_sig).apply_async(link_error=[failure_sig]))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"event=ai_diet_dispatch_failed request_id={request_id} profile_id={profile_id} error={exc!s}")
        return None

    task_id = cast(str | None, getattr(async_result, "id", None))
    if task_id is None:
        logger.error(f"event=ai_diet_missing_task_id request_id={request_id} profile_id={profile_id}")
        return None
    logger.info(f"event=ai_diet_enqueued request_id={request_id} task_id={task_id} profile_id={profile_id}")
    return task_id
