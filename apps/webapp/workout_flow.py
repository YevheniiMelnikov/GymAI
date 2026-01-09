from typing import cast
from uuid import uuid4

from celery import chain
from celery.result import AsyncResult
from loguru import logger
from pydantic import BaseModel, Field, ValidationError, model_validator

from core.ai_coach import AiPlanGenerationPayload
from core.enums import SubscriptionPeriod, WorkoutPlanType, WorkoutLocation
from core.tasks.ai_coach import (
    generate_ai_workout_plan,
    handle_ai_plan_failure,
    notify_ai_plan_ready_task,
)
from django.core.cache import cache
from config.app_settings import settings


class WorkoutPlanRequest(BaseModel):
    plan_type: WorkoutPlanType
    split_number: int = Field(ge=1, le=7)
    period: SubscriptionPeriod | None = None
    wishes: str = ""

    @model_validator(mode="after")
    def _validate_subscription_period(self) -> "WorkoutPlanRequest":
        if self.plan_type is WorkoutPlanType.SUBSCRIPTION and self.period is None:
            raise ValueError("subscription period is required")
        if self.plan_type is WorkoutPlanType.PROGRAM:
            self.period = None
        self.wishes = str(self.wishes or "").strip()
        return self


def enqueue_workout_plan_generation(
    *,
    profile_id: int,
    language: str,
    plan_type: WorkoutPlanType,
    workout_location: WorkoutLocation,
    wishes: str,
    split_number: int,
    period: SubscriptionPeriod | None,
    previous_subscription_id: int | None = None,
) -> str | None:
    request_id = uuid4().hex
    try:
        payload_model = AiPlanGenerationPayload(
            profile_id=profile_id,
            language=language,
            plan_type=plan_type,
            workout_location=workout_location,
            wishes=wishes,
            period=period.value if period else None,
            split_number=split_number,
            previous_subscription_id=previous_subscription_id,
            request_id=request_id,
        )
    except ValidationError as exc:
        logger.error(f"webapp_plan_invalid_payload profile_id={profile_id} request_id={request_id} error={exc!s}")
        return None

    payload = payload_model.model_dump(mode="json")
    headers = {
        "request_id": request_id,
        "profile_id": profile_id,
        "plan_type": plan_type.value,
    }
    options = {"queue": "ai_coach", "routing_key": "ai_coach", "headers": headers}

    logger.info(
        "webapp_plan_generation_start request_id={} profile_id={} plan_type={} split_number={} wishes_len={}",
        request_id,
        profile_id,
        plan_type.value,
        split_number,
        len(wishes or ""),
    )

    try:
        if hasattr(generate_ai_workout_plan, "s"):
            generate_sig = generate_ai_workout_plan.s(payload).set(**options)  # pyrefly: ignore[not-callable]
            notify_sig = notify_ai_plan_ready_task.s().set(  # pyrefly: ignore[not-callable]
                queue="ai_coach",
                routing_key="ai_coach",
                headers=headers,
            )
            failure_sig = handle_ai_plan_failure.s(payload, "create").set(  # pyrefly: ignore[not-callable]
                queue="ai_coach",
                routing_key="ai_coach",
            )
            async_result = cast(
                AsyncResult,
                chain(generate_sig, notify_sig).apply_async(link_error=[failure_sig]),
            )
        else:
            async_result = generate_ai_workout_plan.apply_async(  # pyrefly: ignore[not-callable]
                args=(payload,),
                queue="ai_coach",
                routing_key="ai_coach",
                headers=headers,
            )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"webapp_plan_dispatch_failed profile_id={profile_id} plan_type={plan_type.value} "
            f"request_id={request_id} error={exc!s}"
        )
        return None

    task_id = cast(str | None, getattr(async_result, "id", None))
    if task_id is None:
        logger.error(f"webapp_plan_missing_task_id profile_id={profile_id} request_id={request_id}")
        return None

    cache.set(
        f"generation_status:{request_id}",
        {"status": "queued", "progress": 5, "stage": "queued"},
        timeout=settings.AI_COACH_TIMEOUT,
    )

    logger.debug(
        "webapp_plan_dispatch_success request_id={} profile_id={} plan_type={} task_id={}",
        request_id,
        profile_id,
        plan_type.value,
        task_id,
    )
    return request_id
