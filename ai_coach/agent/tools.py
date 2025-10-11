# pyrefly: ignore-file
# ruff: noqa
"""Tool definitions for the coach agent."""

from time import monotonic

from loguru import logger
from pydantic_ai import ModelRetry, RunContext  # pyrefly: ignore[import-error]
from pydantic_ai.toolsets.function import FunctionToolset  # pyrefly: ignore[import-error]

from core.cache import Cache
from core.exercises import exercise_dict
from core.schemas import DayExercises, Program, Subscription
from core.utils.short_url import short_url
from core.enums import SubscriptionPeriod

from .base import AgentDeps, AgentExecutionAborted

from ..schemas import ProgramPayload
from core.services import get_gif_manager


toolset = FunctionToolset()


def _prepare_tool(ctx: RunContext[AgentDeps], tool_name: str) -> AgentDeps:  # pyrefly: ignore[unsupported-operation]
    deps = ctx.deps
    elapsed = monotonic() - deps.started_at
    if deps.max_run_seconds > 0 and elapsed > deps.max_run_seconds:
        logger.warning(f"agent_tool_timeout client_id={deps.client_id} tool={tool_name} elapsed={elapsed:.2f}")
        raise AgentExecutionAborted("AI coach request timed out", reason="timeout")
    deps.tool_calls += 1
    if deps.max_tool_calls > 0 and deps.tool_calls > deps.max_tool_calls:
        logger.warning(f"agent_tool_limit_exceeded client_id={deps.client_id} tool={tool_name} steps={deps.tool_calls}")
        raise AgentExecutionAborted("AI coach tool budget exhausted", reason="max_tool_calls_exceeded")
    return deps


@toolset.tool
async def tool_search_knowledge(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
    query: str,
    k: int = 6,
) -> list[str]:
    """Search client and global knowledge with top-k limit."""
    from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase

    deps = _prepare_tool(ctx, "tool_search_knowledge")
    client_id = deps.client_id
    normalized_query = query.strip()
    logger.debug(f"tool_search_knowledge client_id={client_id} query='{normalized_query[:80]}' k={k}")
    if not normalized_query:
        raise ModelRetry("Knowledge search requires a non-empty query. Summarize the client's goal before retrying.")
    if deps.knowledge_base_empty:
        logger.warning(
            f"knowledge_search_aborted client_id={client_id} query='{normalized_query[:80]}' reason=knowledge_base_empty"
        )
        raise AgentExecutionAborted("Knowledge base returned no data", reason="knowledge_base_empty")
    if deps.last_knowledge_query == normalized_query and deps.last_knowledge_empty:
        logger.warning(
            f"knowledge_search_repeat client_id={client_id} query='{normalized_query[:80]}' reason=empty_previous"
        )
        raise AgentExecutionAborted("Knowledge search already returned no results", reason="knowledge_base_empty")
    try:
        result = await KnowledgeBase.search(normalized_query, client_id, k)
    except Exception as e:  # pragma: no cover - forward to model
        message = str(e)
        if "Empty graph" in message or "EntityNotFound" in type(e).__name__:
            deps.knowledge_base_empty = True
            deps.last_knowledge_query = normalized_query
            deps.last_knowledge_empty = True
            logger.warning(
                f"knowledge_search_empty client_id={client_id} query='{normalized_query[:80]}' detail={message}"
            )
            return []
        raise ModelRetry(f"Knowledge search failed: {e}. Refine the query and retry.") from e
    deps.last_knowledge_query = normalized_query
    deps.last_knowledge_empty = len(result) == 0
    if deps.last_knowledge_empty:
        deps.knowledge_base_empty = True
        logger.warning(
            f"knowledge_search_empty client_id={client_id} query='{normalized_query[:80]}' detail=no_results"
        )
    logger.debug(f"tool_search_knowledge results={len(result)}")
    return result


@toolset.tool
async def tool_get_chat_history(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
    limit: int = 20,
) -> list[str]:
    """Load recent chat messages for context."""
    from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase

    deps = _prepare_tool(ctx, "tool_get_chat_history")
    client_id = deps.client_id
    logger.debug(f"tool_get_chat_history client_id={client_id} limit={limit}")
    try:
        if deps.cached_history is None:
            history = await KnowledgeBase.get_message_history(client_id, limit)
            deps.cached_history = history
        else:
            history = deps.cached_history
        if limit is None:
            return list(history)
        return list(history[:limit])
    except Exception as e:  # pragma: no cover - forward to model
        raise ModelRetry(f"Chat history unavailable: {e}. Try calling again.") from e


@toolset.tool
async def tool_save_program(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
    plan: "ProgramPayload",
) -> Program:
    """Persist generated plan for the current client."""
    from core.services import APIService
    from .coach import ProgramAdapter

    deps = _prepare_tool(ctx, "tool_save_program")
    if not deps.allow_save:
        raise RuntimeError("saving not allowed in this mode")
    client_id = deps.client_id
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
    except Exception as e:  # pragma: no cover - forward to model
        raise ModelRetry(f"Program saving failed: {e}. Ensure plan data is valid and retry.") from e


@toolset.tool
async def tool_get_program_history(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
) -> list[Program]:
    """Return client's previous programs."""
    from core.services import APIService

    deps = _prepare_tool(ctx, "tool_get_program_history")
    client_id = deps.client_id
    logger.debug(f"tool_get_program_history client_id={client_id}")
    try:
        return await APIService.workout.get_all_programs(client_id)
    except Exception as e:  # pragma: no cover - forward to model
        raise ModelRetry(f"Program history unavailable: {e}. Try calling the tool again later.") from e


@toolset.tool
async def tool_attach_gifs(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
    exercises: list[DayExercises],
) -> list[DayExercises]:
    """Attach GIF links to exercises if available."""
    deps = _prepare_tool(ctx, "tool_attach_gifs")
    client_id = deps.client_id
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

    deps = _prepare_tool(ctx, "tool_create_subscription")
    if not deps.allow_save:
        raise RuntimeError("saving not allowed in this mode")
    client_id = deps.client_id
    logger.debug(f"tool_create_subscription client_id={client_id} period={period} days={workout_days}")
    exercises_payload = [d.model_dump() for d in exercises]
    price_map = {
        SubscriptionPeriod.one_month: int(settings.REGULAR_AI_SUBSCRIPTION_PRICE),
        SubscriptionPeriod.six_months: int(settings.LARGE_AI_SUBSCRIPTION_PRICE),
    }
    price = price_map.get(period, int(settings.REGULAR_AI_SUBSCRIPTION_PRICE))
    try:
        sub_id = await APIService.workout.create_subscription(
            client_profile_id=client_id,
            workout_days=workout_days,
            wishes=wishes or "",
            amount=Decimal(price),
            period=period,
            exercises=exercises_payload,
        )
        if sub_id is None:
            raise ModelRetry("Subscription creation failed. Adjust provided data and retry.")
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
    except ModelRetry:
        raise
    except Exception as e:  # pragma: no cover - forward to model
        raise ModelRetry(f"Subscription creation failed: {e}. Verify inputs and try again.") from e
