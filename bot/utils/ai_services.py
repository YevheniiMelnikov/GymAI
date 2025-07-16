from decimal import Decimal
from aiogram import Bot
from aiogram.fsm.context import FSMContext

from core.ai_coach.utils import ai_coach_request, ai_assign_client
from core.ai_coach.prompts import PROGRAM_PROMPT, SUBSCRIPTION_PROMPT
from core.ai_coach.parsers import (
    parse_program_text,
    parse_program_json,
    parse_subscription_json,
)
from core.ai_coach.schemas import ProgramRequest, SubscriptionRequest
from loguru import logger
from core.cache import Cache
from core.schemas import Client
from bot.utils.workout_plans import _next_payment_date
from bot.utils.chat import send_program
from core.services.internal import APIService


async def generate_program(client: Client, workout_type: str, wishes: str, state: FSMContext, bot: Bot) -> None:
    await ai_assign_client(client)
    req = ProgramRequest(workout_type=workout_type, wishes=wishes)
    data = await state.get_data()
    lang = data.get("lang")
    prompt = PROGRAM_PROMPT.format(
        request=req.model_dump_json(indent=2),
        language=lang,
        wishes=wishes,
        workout_type=workout_type,
    )
    response = await ai_coach_request(text=prompt, client=client, chat_id=client.id, language=lang)
    logger.debug(f"AI coach response: {response}")
    program_raw = response[0] if response else ""
    program_dto = parse_program_json(program_raw)
    if program_dto is not None:
        exercises = program_dto.days
        split_number = len(exercises)
    else:
        exercises, split_number = parse_program_text(program_raw)
    saved = await APIService.workout.save_program(client.id, exercises, split_number, wishes)
    if saved:
        await Cache.workout.save_program(
            client.profile,
            {
                "id": saved.id,
                "client_profile": client.profile,
                "exercises_by_day": [d.model_dump() for d in exercises],
                "created_at": saved.created_at,
                "split_number": split_number,
                "workout_type": workout_type,
                "wishes": wishes,
                "program_text": program_raw,
            },
        )
    data = await state.get_data()
    from bot.utils.exercises import format_full_program

    program_text = await format_full_program(exercises)
    await send_program(client, data.get("lang", "ua"), program_text, state, bot)


async def generate_subscription(
    client: Client,
    workout_type: str,
    wishes: str,
    period: str,
    workout_days: list[str],
    state: FSMContext,
    bot: Bot,
) -> None:
    await ai_assign_client(client)
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
    response = await ai_coach_request(text=prompt, client=client, chat_id=client.id, language=lang)
    sub_raw = response[0] if response else ""
    sub_dto = parse_subscription_json(sub_raw)
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

    return
