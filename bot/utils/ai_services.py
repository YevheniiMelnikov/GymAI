from decimal import Decimal
import json
from aiogram import Bot
from aiogram.fsm.context import FSMContext

from bot.states import States

from core.ai_coach.utils import ai_coach_request
from config.env_settings import settings
from core.ai_coach.prompts import (
    PROGRAM_PROMPT,
    SUBSCRIPTION_PROMPT,
    SYSTEM_MESSAGE,
)
from core.ai_coach.parsers import (
    parse_program_text,
    parse_program_json,
    parse_subscription_json,
    extract_json,
    normalize_program_data,
)
from core.ai_coach.schemas import ProgramRequest, SubscriptionRequest
from loguru import logger
from core.cache import Cache
from core.exceptions import ProgramNotFoundError
from core.schemas import Client
from bot.utils.workout_plans import _next_payment_date
from bot.utils.chat import send_program, send_message
from bot.texts.text_manager import msg_text
from core.services.internal import APIService


def _normalise_program(raw: str) -> dict:
    """Extract and clean JSON workout program from ``raw`` text."""
    extracted = extract_json(raw)
    if not extracted:
        raise ValueError("no JSON found")
    data = json.loads(extracted)
    normalize_program_data(data)
    return data


async def generate_program(client: Client, workout_type: str, wishes: str, state: FSMContext, bot: Bot) -> None:
    req = ProgramRequest(workout_type=workout_type, wishes=wishes)
    data = await state.get_data()
    lang = data.get("lang")
    details = {
        "name": client.name,
        "gender": client.gender,
        "born_in": client.born_in,
        "weight": client.weight,
        "health_notes": client.health_notes,
        "workout_experience": client.workout_experience,
        "workout_goals": client.workout_goals,
    }
    client_profile = json.dumps({k: v for k, v in details.items() if v is not None}, ensure_ascii=False)
    try:
        prev_program = await Cache.workout.get_latest_program(client.profile, use_fallback=False)
        previous_program = json.dumps([d.model_dump() for d in prev_program.exercises_by_day], ensure_ascii=False)
    except ProgramNotFoundError:
        previous_program = "[]"

    prompt = (
        SYSTEM_MESSAGE
        + "\n\n"
        + PROGRAM_PROMPT.format(
            client_profile=client_profile,
            previous_program=previous_program,
            request=req.model_dump_json(indent=2),
            language=lang,
        )
    )
    program_raw = ""
    program_dto = None
    for _ in range(settings.AI_GENERATION_RETRIES):
        response = await ai_coach_request(text=prompt, client=client, chat_id=client.id, language=lang)
        print(f"Response: {response}")
        program_raw = response[0] if response else ""
        program_dto = parse_program_json(program_raw)
        if program_dto is not None:
            break
    if program_dto is not None:
        exercises = program_dto.days
        split_number = len(exercises)
    else:
        exercises, split_number = parse_program_text(program_raw)

    if not exercises:
        await send_message(
            recipient=client,
            text=msg_text("ai_program_error", lang),
            bot=bot,
            state=state,
            include_incoming_message=False,
        )
        logger.error("Program parsing produced no exercises")
        return
    saved = await APIService.workout.save_program(client.id, exercises, split_number, wishes)
    if saved:
        try:
            program_dict = _normalise_program(program_raw)
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
            # rename key if needed for cache schema
            if "days" in program_dict and "exercises_by_day" not in program_dict:
                program_dict["exercises_by_day"] = program_dict.pop("days")
            await Cache.workout.save_program(client.profile, program_dict)
            logger.info(f"Program generated for client_id={client.id}")
        except Exception as e:
            logger.error(f"Program normalisation failed: {e}")
    data = await state.get_data()
    from bot.utils.exercises import format_program

    program_text = await format_program(exercises, day=0)
    await send_program(client, data.get("lang", "ua"), program_text, state, bot)
    await state.update_data(
        exercises=[d.model_dump() for d in exercises],
        split=len(exercises),
        day_index=0,
        client=True,
    )
    await state.set_state(States.program_view)


async def generate_subscription(
    client: Client,
    workout_type: str,
    wishes: str,
    period: str,
    workout_days: list[str],
    state: FSMContext,
    bot: Bot,
) -> None:
    req = SubscriptionRequest(
        workout_type=workout_type,
        wishes=wishes,
        period=period,
        days=len(workout_days),
        workout_days=workout_days,
    )
    data = await state.get_data()
    lang = data.get("lang")
    prompt = SUBSCRIPTION_PROMPT.format(
        request=req.model_dump_json(indent=2),
        language=lang,
        wishes=wishes,
        workout_days=", ".join(workout_days),
        workout_type=workout_type,
    )
    sub_raw = ""
    sub_dto = None
    for _ in range(settings.AI_GENERATION_RETRIES):
        response = await ai_coach_request(text=prompt, client=client, chat_id=client.id, language=lang)
        sub_raw = response[0] if response else ""
        sub_dto = parse_subscription_json(sub_raw)
        if sub_dto is not None:
            break
    exercises = sub_dto.exercises if sub_dto is not None else []
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

    return
