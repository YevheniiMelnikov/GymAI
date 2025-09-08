from __future__ import annotations

from typing import Any, Sequence, TYPE_CHECKING, Callable
import inspect
import sys

from loguru import logger

try:  # pragma: no cover - optional dependency
    from pydantic_ai import RunContext
except Exception:  # pragma: no cover - optional dependency
    RunContext = Any  # type: ignore[assignment]

from core.cache import Cache
from core.resources.exercises import exercise_dict
from core.schemas import DayExercises, Program, Subscription
from core.services import get_gif_manager
from core.utils.short_url import short_url

from .base import AgentDeps

if TYPE_CHECKING:  # pragma: no cover
    from ..schemas import ProgramPayload


async def tool_get_client_context(ctx: RunContext[AgentDeps], query: str) -> dict[str, Sequence[str]]:
    """Return personal context for a client by query."""

    from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase

    client_id = ctx.deps.client_id
    logger.debug(f"tool_get_client_context client_id={client_id} query={query}")
    return await KnowledgeBase.get_client_context(client_id, query)


async def tool_search_knowledge(ctx: RunContext[AgentDeps], query: str, k: int = 6) -> list[str]:
    """Search global knowledge base with top-k limit."""

    from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase

    logger.debug(f"tool_search_knowledge query='{query[:80]}' k={k}")
    result = await KnowledgeBase.search_knowledge(query, k)
    logger.debug(f"tool_search_knowledge results={len(result)}")
    return result


async def tool_save_program(ctx: RunContext[AgentDeps], plan: "ProgramPayload") -> Program:
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


async def tool_get_program_history(ctx: RunContext[AgentDeps]) -> list[Program]:
    """Return client's previous programs."""

    from core.services import APIService

    client_id = ctx.deps.client_id
    logger.debug(f"tool_get_program_history client_id={client_id}")
    return await APIService.workout.get_all_programs(client_id)


async def tool_attach_gifs(ctx: RunContext[AgentDeps], exercises: list[DayExercises]) -> list[DayExercises]:
    """Attach GIF links to exercises if available."""

    client_id = ctx.deps.client_id
    logger.debug(f"tool_attach_gifs client_id={client_id}")
    gif_manager = get_gif_manager()
    result: list[DayExercises] = []
    for day in exercises:
        new_day = DayExercises(day=day.day, exercises=[])
        for ex in day.exercises:
            link = await gif_manager.find_gif(ex.name, exercise_dict)
            ex_copy = ex.model_copy()
            if link:
                short = await short_url(link)
                ex_copy.gif_link = short
                try:
                    await Cache.workout.cache_gif_filename(ex.name, link.split("/")[-1])
                except Exception as e:  # pragma: no cover - cache errors ignored
                    logger.debug(f"cache_gif_filename failed name={ex.name} err={e}")
            new_day.exercises.append(ex_copy)
        result.append(new_day)
    return result


async def tool_create_subscription(
    ctx: RunContext[AgentDeps],
    period: str,
    workout_days: list[str],
    exercises: list[DayExercises],
    wishes: str | None = None,
) -> Subscription:
    """Create a subscription and return its summary."""

    from decimal import Decimal

    from core.services import APIService
    from core.utils.billing import next_payment_date

    if not ctx.deps.allow_save:
        raise RuntimeError("saving not allowed in this mode")
    client_id = ctx.deps.client_id
    logger.debug(f"tool_create_subscription client_id={client_id} period={period} days={workout_days}")
    exercises_payload = [d.model_dump() for d in exercises]
    sub_id = await APIService.workout.create_subscription(
        client_profile_id=client_id,
        workout_days=workout_days,
        wishes=wishes or "",
        amount=Decimal("0"),
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
        "price": 0,
        "workout_type": "",
        "wishes": wishes or "",
        "period": period,
        "workout_days": workout_days,
        "exercises": exercises_payload,
        "payment_date": payment_date,
    }
    return Subscription.model_validate(data)


def get_all_tools(include: Callable[[str, Callable[..., Any]], bool] | None = None) -> list[Callable[..., Any]]:
    module = sys.modules[__name__]
    funcs: list[Callable[..., Any]] = []
    for name, obj in inspect.getmembers(module, inspect.iscoroutinefunction):
        if not name.startswith("tool_"):
            continue
        if include is None or include(name, obj):
            funcs.append(obj)
    funcs.sort(key=lambda f: f.__name__)
    return funcs
