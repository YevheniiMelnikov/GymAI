from loguru import logger

from pydantic_ai import RunContext
from pydantic_ai.toolsets.function import FunctionToolset

from core.cache import Cache
from core.resources.exercises import exercise_dict
from core.schemas import DayExercises, Program, Subscription
from core.utils.short_url import short_url
from core.enums import SubscriptionPeriod

from .base import AgentDeps

from ..schemas import ProgramPayload
from core.services import get_gif_manager


toolset = FunctionToolset()


@toolset.tool
async def tool_search_knowledge(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
    query: str,
    k: int = 6,
) -> list[str]:
    """Search client and global knowledge with top-k limit."""
    from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase

    client_id = ctx.deps.client_id
    logger.debug(f"tool_search_knowledge client_id={client_id} query='{query[:80]}' k={k}")
    result = await KnowledgeBase.search(query, client_id, k)
    logger.debug(f"tool_search_knowledge results={len(result)}")
    return result


@toolset.tool
async def tool_save_program(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
    plan: "ProgramPayload",
) -> Program:
    """Persist generated plan for the current client."""
    from core.services import APIService
    from .coach import ProgramAdapter

    if not ctx.deps.allow_save:
        raise RuntimeError("saving not allowed in this mode")
    client_id = ctx.deps.client_id
    logger.debug(f"tool_save_program client_id={client_id}")
    program = ProgramAdapter.to_domain(plan)
    try:
        saved = await APIService.workout.save_program(
            client_profile_id=client_id,
            exercises=program.exercises_by_day,
            split_number=program.split_number or len(program.exercises_by_day),
            wishes=program.wishes or "",
        )
        logger.debug(f"event=save_program.success program_id={saved.id} client_id={client_id}")
        return saved
    except Exception as e:  # pragma: no cover - log and re-raise
        logger.error(f"Failed to save program for user {client_id}: {e}")
        raise


@toolset.tool
async def tool_get_program_history(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
) -> list[Program]:
    """Return client's previous programs."""
    from core.services import APIService

    client_id = ctx.deps.client_id
    logger.debug(f"tool_get_program_history client_id={client_id}")
    return await APIService.workout.get_all_programs(client_id)


@toolset.tool
async def tool_attach_gifs(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
    exercises: list[DayExercises],
) -> list[DayExercises]:
    """Attach GIF links to exercises if available."""
    client_id = ctx.deps.client_id
    logger.debug(f"tool_attach_gifs client_id={client_id}")
    try:
        gif_manager = get_gif_manager()
    except Exception as e:  # pragma: no cover - optional service
        logger.warning(f"gif manager unavailable: {e}")
        return exercises

    result: list[DayExercises] = []
    for day in exercises:
        new_day = DayExercises(day=day.day, exercises=[])
        for ex in day.exercises:
            try:
                link = await gif_manager.find_gif(ex.name, exercise_dict)
            except Exception as e:
                logger.debug(f"find_gif failed name={ex.name} err={e}")
                link = None

            ex_copy = ex.model_copy()
            if link:
                try:
                    short = await short_url(link)
                except Exception as e:
                    logger.debug(f"short_url failed link={link} err={e}")
                    short = link
                ex_copy.gif_link = short
                try:
                    await Cache.workout.cache_gif_filename(ex.name, link.split("/")[-1])
                except Exception as e:  # pragma: no cover - cache errors ignored
                    logger.debug(f"cache_gif_filename failed name={ex.name} err={e}")
            new_day.exercises.append(ex_copy)
        result.append(new_day)
    return result


@toolset.tool
async def tool_create_subscription(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
    workout_days: list[str],
    exercises: list[DayExercises],
    period: SubscriptionPeriod = SubscriptionPeriod.one_month,
    wishes: str | None = None,
) -> Subscription:
    """Create a subscription and return its summary."""
    from decimal import Decimal

    from core.services import APIService
    from core.utils.billing import next_payment_date
    from config.app_settings import settings

    if not ctx.deps.allow_save:
        raise RuntimeError("saving not allowed in this mode")
    client_id = ctx.deps.client_id
    logger.debug(f"tool_create_subscription client_id={client_id} period={period} days={workout_days}")
    exercises_payload = [d.model_dump() for d in exercises]
    price_map = {
        SubscriptionPeriod.one_month: int(settings.REGULAR_AI_SUBSCRIPTION_PRICE),
        SubscriptionPeriod.six_months: int(settings.LARGE_AI_SUBSCRIPTION_PRICE),
    }
    price = price_map.get(period, int(settings.REGULAR_AI_SUBSCRIPTION_PRICE))
    sub_id = await APIService.workout.create_subscription(
        client_profile_id=client_id,
        workout_days=workout_days,
        wishes=wishes or "",
        amount=Decimal(price),
        period=period,
        exercises=exercises_payload,
    )
    if sub_id is None:
        raise RuntimeError("subscription creation failed")
    payment_date = next_payment_date(period)
    await APIService.workout.update_subscription(sub_id, {"enabled": True, "payment_date": payment_date})
    logger.debug(f"event=create_subscription.success subscription_id={sub_id} payment_date={payment_date}")
    sub = await APIService.workout.get_latest_subscription(client_id)
    if sub is not None:
        return sub
    data = {
        "id": sub_id,
        "client_profile": client_id,
        "enabled": True,
        "price": price,
        "workout_type": "",
        "wishes": wishes or "",
        "period": period.value,
        "workout_days": workout_days,
        "exercises": exercises_payload,
        "payment_date": payment_date,
    }
    return Subscription.model_validate(data)
