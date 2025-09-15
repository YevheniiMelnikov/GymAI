from loguru import logger

from core.cache import Cache
from core.schemas import Client, DayExercises, Program, Subscription
from core.services.internal import APIService
from core.enums import WorkoutPlanType, WorkoutType


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
    profile_id = client.profile
    logger.debug(f"generate_workout_plan request_id={request_id} profile_id={profile_id} type={plan_type}")
    plan = await APIService.ai_coach.create_workout_plan(
        plan_type,
        client_id=profile_id,
        language=language,
        period=period,
        workout_days=workout_days,
        wishes=wishes,
        workout_type=workout_type,
        request_id=request_id,
    )
    if not plan:
        logger.error(f"Workout plan generation failed profile_id={profile_id}")
        return []
    if plan_type is WorkoutPlanType.PROGRAM:
        assert isinstance(plan, Program)
        await Cache.workout.save_program(client.id, plan.model_dump())
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
