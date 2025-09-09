from loguru import logger

from core.cache import Cache
from core.schemas import Client, DayExercises, Program
from core.services.internal import APIService


async def generate_program(
    client: Client,
    language: str,
    workout_type: str,
    wishes: str,
    *,
    request_id: str,
) -> list[DayExercises]:
    prompt = f"The client requests a {workout_type} program. Wishes: {wishes}"
    logger.debug(f"generate_program request_id={request_id} client_id={client.id}")
    program = await APIService.ai_coach.create_program(
        prompt,
        client_id=client.id,
        language=language,
        wishes=wishes,
        request_id=request_id,
    )
    if not program:
        logger.error(f"Program generation failed client_id={client.id}")
        return []
    await Cache.workout.save_program(client.id, program.model_dump())
    return program.exercises_by_day


async def generate_subscription(
    client: Client,
    language: str,
    workout_type: str,
    wishes: str,
    period: str,
    workout_days: list[str],
) -> list[DayExercises]:
    prompt = (
        f"The client requests a {workout_type} program for a {period} subscription. "
        f"Wishes: {wishes}. Preferred days: {', '.join(workout_days)}."
    )
    subscription = await APIService.ai_coach.create_subscription(
        prompt,
        client_id=client.id,
        language=language,
        period=period,
        workout_days=workout_days,
        wishes=wishes,
    )
    if not subscription:
        logger.error(f"Subscription generation failed client_id={client.id}")
        return []
    await Cache.workout.save_subscription(client.profile, subscription.model_dump())
    return subscription.exercises


async def process_workout_result(
    client_id: int,
    expected_workout_result: str,
    feedback: str,
    language: str,
) -> Program:
    prompt = "Update workout program based on client feedback"
    program = await APIService.ai_coach.update_program(
        prompt,
        client_id=client_id,
        language=language,
        expected_workout=expected_workout_result,
        feedback=feedback,
    )
    if not program:
        logger.error(f"Workout update failed client_id={client_id}")
        return Program(
            id=0,
            client_profile=client_id,
            exercises_by_day=[],
            created_at=0.0,
            split_number=0,
            workout_type="",
            wishes="",
        )
    return program
