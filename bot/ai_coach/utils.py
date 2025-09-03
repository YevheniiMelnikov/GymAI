from __future__ import annotations

from loguru import logger

from core.cache import Cache
from core.schemas import Client, DayExercises, Program, Subscription
from core.services.internal import APIService


async def generate_program(
    client: Client,
    language: str,
    workout_type: str,
    wishes: str,
    *,
    request_id: str,
) -> list[DayExercises]:
    """Request and cache a workout program via the AI coach service."""
    prompt = f"The client requests a {workout_type} program. Wishes: {wishes}"
    logger.debug("generate_program request_id={} client_id={}", request_id, client.id)
    data = await APIService.ai_coach.ask(
        prompt,
        client_id=client.id,
        language=language,
        mode="program",
        request_id=request_id,
    )
    if not data:
        logger.error("Program generation failed client_id={}", client.id)
        return []
    program = Program.model_validate(data)
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
    """Request and cache a subscription workout plan."""
    prompt = (
        f"The client requests a {workout_type} program for a {period} subscription. "
        f"Wishes: {wishes}. Preferred days: {', '.join(workout_days)}."
    )
    data = await APIService.ai_coach.ask(
        prompt,
        client_id=client.id,
        language=language,
        mode="subscription",
        period=period,
        workout_days=workout_days,
    )
    if not data:
        logger.error("Subscription generation failed client_id={}", client.id)
        return []
    if "exercises" not in data and "exercises_by_day" in data:
        data["exercises"] = data.pop("exercises_by_day")
    subscription = Subscription.model_validate(data)
    await Cache.workout.save_subscription(client.profile, subscription.model_dump())
    return subscription.exercises


async def process_workout_result(
    client_id: int,
    expected_workout_result: str,
    feedback: str,
    language: str,
) -> Program:
    """Update a program based on client feedback."""
    prompt = "Update workout program based on client feedback"
    data = await APIService.ai_coach.ask(
        prompt,
        client_id=client_id,
        language=language,
        mode="update",
        expected_workout=expected_workout_result,
        feedback=feedback,
    )
    if not data:
        logger.error("Workout update failed client_id={}", client_id)
        return Program(
            id=0,
            client_profile=client_id,
            exercises_by_day=[],
            created_at=0.0,
            split_number=0,
            workout_type="",
            wishes="",
        )
    return Program.model_validate(data)
