from decimal import Decimal
import json
from typing import Callable, Optional, TypeVar

from core.services.internal import APIService
from config.app_settings import settings
from .prompts import (
    WORKOUT_PLAN_PROMPT,
    PROGRAM_RESPONSE_TEMPLATE,
    SUBSCRIPTION_RESPONSE_TEMPLATE,
    WORKOUT_RULES,
    SYSTEM_PROMPT,
    UPDATE_WORKOUT_PROMPT,
    INITIAL_PROMPT,
)
from .parsers import (
    parse_program_text,
    parse_program_json,
    parse_subscription_json,
    extract_json,
    normalize_program_data,
)
from loguru import logger
from core.cache import Cache
from core.exceptions import ProgramNotFoundError
from core.schemas import Client, Program, DayExercises
from bot.utils.workout_plans import _next_payment_date
from datetime import date

T = TypeVar("T")


def extract_client_data(client: Client) -> str:
    details = {
        "name": client.name,
        "gender": client.gender,
        "born_in": client.born_in,
        "weight": client.weight,
        "health_notes": client.health_notes,
        "workout_experience": client.workout_experience,
        "workout_goals": client.workout_goals,
    }
    clean = {k: v for k, v in details.items() if v is not None}
    return json.dumps(clean, ensure_ascii=False)


def describe_client(client: Client) -> str:
    """Return natural language description of ``client``."""

    today = date.today()
    parts: list[str] = []
    if client.name:
        parts.append(f"Name: {client.name}")
    if client.gender:
        parts.append(f"Gender: {client.gender}")
    if client.born_in:
        try:
            age = today.year - int(client.born_in)
            parts.append(f"Age: {age}")
        except ValueError:
            pass
    if client.weight:
        parts.append(f"Weight: {client.weight} kg")
    if client.workout_experience:
        if client.workout_experience == "5+":
            exp_text = "Training experience: 5 or more years (maximum option in the questionnaire)"
        else:
            exp_text = f"Training experience: {client.workout_experience} years"
        parts.append(exp_text)
    if client.workout_goals:
        parts.append(f"Goals: {client.workout_goals}")
    if client.health_notes:
        parts.append(f"Health notes: {client.health_notes}")
    return "; ".join(parts)


async def assign_client(client: Client, lang: str) -> None:
    prompt = INITIAL_PROMPT.format(
        client_data=extract_client_data(client),
        language=lang,
    )
    await APIService.ai_coach.ask(prompt, client_id=client.id)


def _normalise_program(raw: str, *, key: str = "days") -> dict:
    """Extract and clean JSON workout data from ``raw`` text."""

    extracted = extract_json(raw)
    if not extracted:
        raise ValueError("no JSON found")
    data = json.loads(extracted)
    normalize_program_data(data, key=key)
    return data


async def _cache_program(
    client: Client,
    program_raw: str,
    saved: Program,
    workout_type: str,
    wishes: str,
) -> None:
    """Normalise ``program_raw`` and store result in cache."""

    try:
        program_dict = _normalise_program(program_raw)
    except Exception as e:  # pragma: no cover - log and continue
        logger.error(f"Program normalisation failed: {e}")
        return

    program_dict.update(
        {
            "id": saved.id,
            "client_profile": client.profile,
            "created_at": saved.created_at,
            "split_number": len(program_dict.get("days", [])),
            "workout_type": workout_type,
            "wishes": wishes,
            "program_text": program_raw,
        }
    )

    if "days" in program_dict and "exercises_by_day" not in program_dict:
        program_dict["exercises_by_day"] = program_dict.pop("days")

    await Cache.workout.save_program(client.profile, program_dict)
    logger.info(f"Program generated for client_id={client.id}")


async def _generate_workout(
    client: Client,
    lang: str,
    request_context: str,
    response_template: str,
    parser: Callable[[str], Optional[T]],
) -> tuple[str, Optional[T]]:
    """Request workout plan from AI and parse result."""

    profile_description = describe_client(client)
    today = date.today().isoformat()
    prompt = (
        SYSTEM_PROMPT
        + "\n\n"
        + WORKOUT_PLAN_PROMPT.format(
            client_profile=profile_description,
            request_context=request_context,
            language=lang,
            current_date=today,
            workout_rules=WORKOUT_RULES,
            response_template=response_template,
        )
    )
    raw = ""
    dto: Optional[T] = None
    for _ in range(settings.AI_GENERATION_RETRIES):
        response = await APIService.ai_coach.ask(prompt, client_id=client.id, language=lang)
        raw = response[0] if response else ""
        dto = parser(raw)
        if dto is not None:
            break
    return raw, dto


async def generate_program(
    client: Client, lang: str, workout_type: str, wishes: str
) -> tuple[list[DayExercises], str]:
    try:
        prev_program = await Cache.workout.get_latest_program(client.profile, use_fallback=False)
        previous_program = json.dumps([d.model_dump() for d in prev_program.exercises_by_day], ensure_ascii=False)
    except ProgramNotFoundError:
        previous_program = "[]"

    request_context = (
        f"Previous program (JSON):\n{previous_program}\n\n"
        f"The client requests a {workout_type} program. Additional wishes: {wishes}."
    )

    program_raw, program_dto = await _generate_workout(
        client,
        lang,
        request_context,
        PROGRAM_RESPONSE_TEMPLATE,
        parse_program_json,
    )
    if program_dto is not None:
        exercises = program_dto.days
        split_number = len(exercises)
    else:
        try:
            prog_dict = _normalise_program(program_raw, key="days")
            exercises = [DayExercises.model_validate(d) for d in prog_dict.get("days", [])]
            split_number = len(exercises)
        except Exception:
            exercises, split_number = parse_program_text(program_raw)

    if not exercises:
        logger.error("Program parsing produced no exercises")
        return [], program_raw
    saved = await APIService.workout.save_program(client.id, exercises, split_number, wishes)
    if saved:
        await _cache_program(client, program_raw, saved, workout_type, wishes)
    return exercises, program_raw


async def generate_subscription(
    client: Client,
    lang: str,
    workout_type: str,
    wishes: str,
    period: str,
    workout_days: list[str],
) -> tuple[list[DayExercises], str]:
    request_context = (
        f"The client requests a {workout_type} program for a {period} subscription.\n"
        f"Wishes: {wishes}.\n"
        f"Preferred workout days: {', '.join(workout_days)} (total {len(workout_days)} days per week)."
    )

    sub_raw, sub_dto = await _generate_workout(
        client,
        lang,
        request_context,
        SUBSCRIPTION_RESPONSE_TEMPLATE,
        parse_subscription_json,
    )
    if sub_dto is not None:
        exercises = sub_dto.exercises
    else:
        try:
            sub_dict = _normalise_program(sub_raw, key="exercises")
            exercises = [DayExercises.model_validate(d) for d in sub_dict.get("exercises", [])]
        except Exception:
            exercises, _ = parse_program_text(sub_raw)

    if not exercises:
        logger.error("Subscription parsing produced no exercises")
        return [], sub_raw

    sub_id = await APIService.workout.create_subscription(
        client_profile_id=client.id,
        workout_days=workout_days,
        wishes=wishes,
        amount=Decimal("0"),
        period=period,
        exercises=[e.model_dump() for e in exercises],
    )
    if sub_id:
        next_payment = _next_payment_date(period)
        await APIService.workout.update_subscription(sub_id, {"enabled": True, "payment_date": next_payment})
        await Cache.workout.save_subscription(
            client.profile,
            {
                "id": sub_id,
                "enabled": True,
                "payment_date": next_payment,
                "workout_type": workout_type,
                "wishes": wishes,
                "workout_days": workout_days,
                "period": period,
                "exercises": [d.model_dump() for d in exercises],
            },
        )
        logger.info(f"New AI-coach subscription generated for client_id={client.id}")

    return exercises, sub_raw


async def process_workout_result(
    client_id: int,
    expected_workout_result: str,
    feedback: str,
    language: str,
) -> str:
    """Return updated workout plan for ``client_id`` based on ``feedback``."""

    try:
        ctx = await APIService.ai_coach.get_client_context(client_id, "workout")
    except Exception:
        ctx = {"messages": [], "prompts": []}

    prompt = (
        SYSTEM_PROMPT
        + "\n\n"
        + UPDATE_WORKOUT_PROMPT.format(
            expected_workout=expected_workout_result.strip(),
            feedback=feedback.strip(),
            context="\n".join(ctx["messages"] + ctx["prompts"]).strip(),
            language=language,
        )
    )

    responses = await APIService.ai_coach.ask(prompt, client_id=client_id)
    return responses[0] if responses else ""
