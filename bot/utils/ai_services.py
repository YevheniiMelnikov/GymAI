from decimal import Decimal
from aiogram import Bot
from aiogram.fsm.context import FSMContext

from core.ai_coach.utils import ai_coach_request, ai_assign_client
from core.ai_coach.prompts import PROGRAM_PROMPT, SUBSCRIPTION_PROMPT
from core.ai_coach.parsers import parse_program_text
from core.cache import Cache
from core.schemas import Client
from core.services import APIService
from bot.utils.workout_plans import _next_payment_date
from bot.utils.chat import send_program


async def generate_program(client: Client, workout_type: str, wishes: str, state: FSMContext, bot: Bot) -> None:
    await ai_assign_client(client)
    prompt = PROGRAM_PROMPT.format(workout_type=workout_type, wishes=wishes)
    response = await ai_coach_request(text=prompt)
    program_text = response[0] if response else ""
    exercises, split_number = parse_program_text(program_text)
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
                "program_text": program_text,
            },
        )
    data = await state.get_data()
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
    prompt = SUBSCRIPTION_PROMPT.format(workout_type=workout_type, wishes=wishes, period=period, days=len(workout_days))
    await ai_coach_request(text=prompt)
    sub_id = await APIService.workout.create_subscription(
        client_profile_id=client.id,
        workout_days=workout_days,
        wishes=wishes,
        amount=Decimal("0"),
        period=period,
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
            },
        )

    return
