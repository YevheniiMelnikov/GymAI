from celery.result import AsyncResult
from loguru import logger


from core.cache import Cache
from core.enums import WorkoutPlanType, WorkoutType
from core.schemas import Client, DayExercises, Program, Subscription
from core.services.internal import APIService


async def generate_workout_plan(
    *,
    client: Client,
    language: str,
    plan_type: WorkoutPlanType,
    workout_type: WorkoutType,
    wishes: str,
    request_id: str,
    period: str | None = None,
    workout_days: list[str] | None = None,
) -> list[DayExercises]:
    client_id: int = client.id
    logger.debug(f"generate_workout_plan request_id={request_id} client_id={client_id} type={plan_type}")
    plan = await APIService.ai_coach.create_workout_plan(
        plan_type,
        client_id=client_id,
        language=language,
        period=period,
        workout_days=workout_days,
        wishes=wishes,
        workout_type=workout_type,
        request_id=request_id,
    )
    if not plan:
        logger.error(f"Workout plan generation failed client_id={client_id}")
        return []
    if plan_type is WorkoutPlanType.PROGRAM:
        assert isinstance(plan, Program)
        await Cache.workout.save_program(client.profile, plan.model_dump())
        return plan.exercises_by_day
    assert isinstance(plan, Subscription)
    await Cache.workout.save_subscription(client.profile, plan.model_dump())
    return plan.exercises


async def process_workout_plan_result(
    *,
    client_id: int,
    expected_workout_result: str,
    feedback: str,
    language: str,
    plan_type: WorkoutPlanType,
) -> Program | Subscription:
    plan = await APIService.ai_coach.update_workout_plan(
        plan_type,
        client_id=client_id,
        language=language,
        expected_workout=expected_workout_result,
        feedback=feedback,
    )
    if plan:
        return plan
    logger.error(f"Workout update failed client_id={client_id}")
    if plan_type is WorkoutPlanType.PROGRAM:
        return Program(
            id=0,
            client_profile=client_id,
            exercises_by_day=[],
            created_at=0.0,
            split_number=0,
            workout_type="",
            wishes="",
        )
    return Subscription(
        id=0,
        client_profile=client_id,
        enabled=False,
        price=0,
        workout_type="",
        wishes="",
        period="",
        workout_days=[],
        exercises=[],
        payment_date="1970-01-01",
    )


async def enqueue_workout_plan_generation(
    *,
    client: Client,
    language: str,
    plan_type: WorkoutPlanType,
    workout_type: WorkoutType,
    wishes: str,
    request_id: str,
    period: str | None = None,
    workout_days: list[str] | None = None,
) -> bool:
    try:
        from core.tasks import generate_ai_workout_plan  # local import to avoid circular deps
    except Exception as exc:  # pragma: no cover - import failure
        logger.error(f"Celery task import failed request_id={request_id}: {exc}")
        return False

    payload: dict[str, object] = {
        "client_id": client.id,
        "client_profile_id": client.profile,
        "language": language,
        "plan_type": plan_type.value,
        "workout_type": workout_type.value,
        "wishes": wishes,
        "period": period,
        "workout_days": workout_days or [],
        "request_id": request_id,
    }

    try:
        async_result: AsyncResult = generate_ai_workout_plan.apply_async(
            args=(payload,),
            queue="ai_coach",
            routing_key="ai_coach",
        )  # pyrefly: ignore[not-callable]
        logger.debug(
            f"queued_workout_plan_generation client_id={client.id} plan_type={plan_type.value} "
            f"request_id={request_id} task_id={async_result.id}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"Celery dispatch failed client_id={client.id} plan_type={plan_type.value} "
            f"request_id={request_id} error={exc}"
        )
        return False
    return True


async def enqueue_workout_plan_update(
    *,
    client_id: int,
    client_profile_id: int,
    expected_workout_result: str,
    feedback: str,
    language: str,
    plan_type: WorkoutPlanType,
    workout_type: WorkoutType | None,
    request_id: str,
) -> bool:
    try:
        from core.tasks import update_ai_workout_plan  # local import to avoid circular deps
    except Exception as exc:  # pragma: no cover - import failure
        logger.error(f"Celery task import failed request_id={request_id}: {exc}")
        return False

    payload: dict[str, object] = {
        "client_id": client_id,
        "client_profile_id": client_profile_id,
        "language": language,
        "plan_type": plan_type.value,
        "expected_workout_result": expected_workout_result,
        "feedback": feedback,
        "workout_type": workout_type.value if workout_type else None,
        "request_id": request_id,
    }

    try:
        async_result: AsyncResult = update_ai_workout_plan.apply_async(
            args=(payload,),
            queue="ai_coach",
            routing_key="ai_coach",
        )  # pyrefly: ignore[not-callable]
        logger.debug(
            f"queued_workout_plan_update client_id={client_id} plan_type={plan_type.value} "
            f"request_id={request_id} task_id={async_result.id}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"Celery dispatch failed client_id={client_id} plan_type={plan_type.value} "
            f"request_id={request_id} error={exc}"
        )
        return False
    return True
