# pyrefly: ignore-file
# ruff: noqa
"""Tool definitions for the coach agent."""

from asyncio import TimeoutError, wait_for
from time import monotonic
from typing import Any, Callable, Coroutine, TypeVar, cast

from loguru import logger
from pydantic_ai import ModelRetry, RunContext  # pyrefly: ignore[import-error]
from pydantic_ai.tools import ToolDefinition  # pyrefly: ignore[import-error]
from pydantic_ai.toolsets.function import FunctionToolset  # pyrefly: ignore[import-error]

from core.cache import Cache
from core.exercises import exercise_dict
from core.schemas import DayExercises, Program, Subscription
from core.utils.short_url import short_url
from core.enums import SubscriptionPeriod
from config.app_settings import settings

from .base import AgentDeps
from ai_coach.exceptions import AgentExecutionAborted
from ai_coach.types import CoachMode

from ..schemas import ProgramPayload
from core.services import get_gif_manager


toolset = FunctionToolset()

T = TypeVar("T")

DEFAULT_TOOL_TIMEOUT: float = float(settings.AI_COACH_DEFAULT_TOOL_TIMEOUT)
TOOL_TIMEOUTS: dict[str, float] = {
    "tool_search_knowledge": float(settings.AI_COACH_SEARCH_TIMEOUT),
    "tool_get_chat_history": float(settings.AI_COACH_HISTORY_TIMEOUT),
    "tool_get_program_history": float(settings.AI_COACH_PROGRAM_HISTORY_TIMEOUT),
}

TOOL_ALLOWED_MODES: dict[str, set[CoachMode]] = {
    "tool_save_program": {CoachMode.program, CoachMode.update},
    "tool_create_subscription": {CoachMode.subscription},
}


def _tool_timeout(tool_name: str) -> float:
    return TOOL_TIMEOUTS.get(tool_name, DEFAULT_TOOL_TIMEOUT)


def _looks_like_prompt(query: str) -> bool:
    lowered = query.lower()
    if "mode:" in lowered:
        return True
    if "you are an ai coach" in lowered:
        return True
    return False


def _raise_tool_limit(deps: AgentDeps, tool_name: str) -> None:
    mode_value = deps.mode.value if deps.mode else "unknown"
    logger.info(
        f"agent_tool_limit_exceeded client_id={deps.client_id} tool={tool_name} steps={deps.tool_calls} mode={mode_value}"
    )
    raise AgentExecutionAborted("AI coach tool budget exhausted", reason="max_tool_calls_exceeded")


def _prepare_tool(ctx: RunContext[AgentDeps], tool_name: str) -> AgentDeps:  # pyrefly: ignore[unsupported-operation]
    deps = ctx.deps
    elapsed = monotonic() - deps.started_at
    if deps.max_run_seconds > 0 and elapsed > deps.max_run_seconds:
        mode_value = deps.mode.value if deps.mode else "unknown"
        logger.info(
            f"agent_tool_timeout client_id={deps.client_id} tool={tool_name} elapsed={elapsed:.2f} mode={mode_value}"
        )
        raise AgentExecutionAborted("AI coach request timed out", reason="timeout")
    deps.tool_calls += 1
    if deps.max_tool_calls > 0 and deps.tool_calls > deps.max_tool_calls:
        _raise_tool_limit(deps, tool_name)
    return deps


def _log_tool_disabled(deps: AgentDeps, tool_name: str, *, reason: str) -> None:
    if tool_name in deps.disabled_tools:
        return
    deps.disabled_tools.add(tool_name)


def _start_tool(
    ctx: RunContext[AgentDeps], tool_name: str
) -> tuple[AgentDeps, bool, Any]:  # pyrefly: ignore[unsupported-operation]
    deps = ctx.deps
    if tool_name in deps.called_tools:
        _log_tool_disabled(deps, tool_name, reason="tool_repeat_skipped")
        return deps, True, deps.tool_cache.get(tool_name)
    prepared = _prepare_tool(ctx, tool_name)
    prepared.called_tools.add(tool_name)
    return prepared, False, None


def _cache_result(deps: AgentDeps, tool_name: str, result: T) -> T:
    deps.tool_cache[tool_name] = result
    return result


def _single_use_prepare(
    tool_name: str,
) -> Callable[[RunContext[AgentDeps], ToolDefinition], Coroutine[Any, Any, ToolDefinition | None]]:
    async def _prepare(
        ctx: RunContext[AgentDeps], tool_def: ToolDefinition
    ) -> ToolDefinition | None:  # pyrefly: ignore[unsupported-operation]
        deps = ctx.deps
        allowed_modes = TOOL_ALLOWED_MODES.get(tool_name)
        mode = deps.mode
        if allowed_modes is not None and mode is not None and mode not in allowed_modes:
            _log_tool_disabled(deps, tool_name, reason="tool_disabled_for_mode")
            return None
        if mode in (CoachMode.program, CoachMode.subscription) and tool_name in deps.called_tools:
            _log_tool_disabled(deps, tool_name, reason="tool_disabled_after_first_call")
            return None
        return tool_def

    return _prepare


@toolset.tool(prepare=_single_use_prepare("tool_search_knowledge"))
async def tool_search_knowledge(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
    query: str,
    k: int = 6,
) -> list[str]:
    """Search client and global knowledge with top-k limit."""
    from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase

    tool_name = "tool_search_knowledge"
    deps, skipped, cached = _start_tool(ctx, tool_name)
    timeout = _tool_timeout("tool_search_knowledge")
    client_id = deps.client_id
    normalized_query = query.strip()
    logger.debug(f"tool_search_knowledge client_id={client_id} query='{normalized_query[:80]}' k={k}")
    if skipped:
        cached_result = cast(list[str], cached if cached is not None else [])
        return cached_result
    if not normalized_query:
        raise ModelRetry("Knowledge search requires a non-empty query. Summarize the client's goal before retrying.")
    if _looks_like_prompt(normalized_query):
        deps.knowledge_base_empty = True
        deps.last_knowledge_query = normalized_query
        deps.last_knowledge_empty = True
        logger.debug(
            f"knowledge_search_skipped client_id={client_id} query='{normalized_query[:80]}' reason=prompt_guard"
        )
        return _cache_result(deps, tool_name, [])
    if deps.knowledge_base_empty:
        deps.last_knowledge_query = normalized_query
        deps.last_knowledge_empty = True
        logger.info(
            f"knowledge_search_aborted client_id={client_id} query='{normalized_query[:80]}' reason=knowledge_base_empty"
        )
        return _cache_result(deps, tool_name, [])
    if deps.last_knowledge_query == normalized_query and deps.last_knowledge_empty:
        logger.debug(
            f"knowledge_search_repeat client_id={client_id} query='{normalized_query[:80]}' reason=empty_previous"
        )
        return _cache_result(deps, tool_name, [])

    async def _load_fallback(reason: str) -> list[str]:
        try:
            fallback_values = await KnowledgeBase.fallback_entries(client_id, limit=k)
        except Exception as fallback_exc:  # noqa: BLE001 - diagnostics only
            logger.debug(
                "knowledge_search_fallback_failed client_id={} query='{}' reason={} detail={}".format(
                    client_id,
                    normalized_query[:80],
                    reason,
                    fallback_exc,
                )
            )
            fallback_values = []
        trimmed: list[str] = []
        for value in fallback_values:
            text = str(value).strip()
            if text:
                trimmed.append(text)
        deps.last_knowledge_query = normalized_query
        if trimmed:
            deps.last_knowledge_empty = False
            deps.knowledge_base_empty = False
            logger.info(
                "knowledge_search_{}_fallback client_id={} query='{}' entries={}".format(
                    reason,
                    client_id,
                    normalized_query[:80],
                    len(trimmed),
                )
            )
            return _cache_result(deps, tool_name, trimmed)
        deps.last_knowledge_empty = True
        deps.knowledge_base_empty = True
        logger.info(
            "knowledge_search_{} client_id={} query='{}' detail=no_entries".format(
                reason,
                client_id,
                normalized_query[:80],
            )
        )
        return _cache_result(deps, tool_name, [])

    try:
        snippets = await wait_for(
            KnowledgeBase.search(
                normalized_query,
                client_id,
                k,
                request_id=deps.request_rid,
            ),
            timeout=timeout,
        )
    except TimeoutError:
        logger.info(
            "knowledge_search_timeout client_id={} query='{}' timeout={:.1f}".format(
                client_id,
                normalized_query[:80],
                timeout,
            )
        )
        return await _load_fallback("timeout")
    except Exception as e:  # pragma: no cover - forward to model
        message = str(e)
        if "Empty graph" in message or "EntityNotFound" in type(e).__name__:
            return await _load_fallback("empty")
        raise ModelRetry(f"Knowledge search failed: {e}. Refine the query and retry.") from e

    deps.last_knowledge_query = normalized_query
    if snippets:
        deps.last_knowledge_empty = False
        deps.knowledge_base_empty = False
        logger.debug(f"tool_search_knowledge results={len(snippets)}")
        texts = [snippet.text for snippet in snippets]
        return _cache_result(deps, tool_name, texts)

    return await _load_fallback("empty")


@toolset.tool(prepare=_single_use_prepare("tool_get_chat_history"))
async def tool_get_chat_history(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
    limit: int = 20,
) -> list[str]:
    """Load recent chat messages for context."""
    from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase

    tool_name = "tool_get_chat_history"
    deps, skipped, cached = _start_tool(ctx, tool_name)
    timeout = _tool_timeout("tool_get_chat_history")
    client_id = deps.client_id
    logger.debug(f"tool_get_chat_history client_id={client_id} limit={limit}")
    if skipped:
        cached_history = cast(list[str], cached if cached is not None else [])
        return list(cached_history)
    try:
        if deps.cached_history is None:
            history = await wait_for(KnowledgeBase.get_message_history(client_id, limit), timeout=timeout)
            deps.cached_history = history
        else:
            history = deps.cached_history
        if limit is None:
            return _cache_result(deps, tool_name, list(history))
        limited = list(history[:limit])
        return _cache_result(deps, tool_name, limited)
    except TimeoutError:
        logger.info(f"chat_history_timeout client_id={client_id} tool=tool_get_chat_history timeout={timeout}")
        deps.cached_history = deps.cached_history or []
        return _cache_result(deps, tool_name, list(deps.cached_history))
    except Exception as e:  # pragma: no cover - forward to model
        raise ModelRetry(f"Chat history unavailable: {e}. Try calling again.") from e


@toolset.tool(prepare=_single_use_prepare("tool_save_program"))
async def tool_save_program(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
    plan: "ProgramPayload",
) -> Program:
    """Persist generated plan for the current client."""
    from core.services import APIService
    from .coach import ProgramAdapter

    tool_name = "tool_save_program"
    deps, skipped, cached = _start_tool(ctx, tool_name)
    if skipped:
        return cast(Program, cached)
    if not deps.allow_save:
        raise RuntimeError("saving not allowed in this mode")
    client_id = deps.client_id
    logger.debug(f"tool_save_program client_id={client_id}")
    program = ProgramAdapter.to_domain(plan)
    timeout: float = float(settings.AI_COACH_SAVE_TIMEOUT)
    try:
        saved = await wait_for(
            APIService.workout.save_program(
                client_profile_id=client_id,
                exercises=program.exercises_by_day,
                split_number=program.split_number or len(program.exercises_by_day),
                wishes=program.wishes or "",
            ),
            timeout=timeout,
        )
        logger.debug(f"event=save_program.success program_id={saved.id} client_id={client_id}")
        deps.final_result = saved
        return _cache_result(deps, tool_name, saved)
    except TimeoutError:
        logger.info(f"save_program_timeout client_id={client_id} timeout={timeout}")
        deps.final_result = program
        return _cache_result(deps, tool_name, program)
    except Exception as e:  # pragma: no cover - forward to model
        raise ModelRetry(f"Program saving failed: {e}. Ensure plan data is valid and retry.") from e


@toolset.tool(prepare=_single_use_prepare("tool_get_program_history"))
async def tool_get_program_history(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
) -> list[Program]:
    """Return client's previous programs."""
    from core.services import APIService

    tool_name = "tool_get_program_history"
    deps, skipped, cached = _start_tool(ctx, tool_name)
    timeout = _tool_timeout("tool_get_program_history")
    client_id = deps.client_id
    logger.debug(f"tool_get_program_history client_id={client_id}")
    if skipped:
        cached_result = cast(list[Program], cached if cached is not None else [])
        return cached_result
    try:
        history = await wait_for(APIService.workout.get_all_programs(client_id), timeout=timeout)
        return _cache_result(deps, tool_name, history)
    except TimeoutError:
        logger.info(f"program_history_timeout client_id={client_id} tool=tool_get_program_history timeout={timeout}")
        return _cache_result(deps, tool_name, [])
    except Exception as e:  # pragma: no cover - forward to model
        raise ModelRetry(f"Program history unavailable: {e}. Try calling the tool again later.") from e


@toolset.tool(prepare=_single_use_prepare("tool_attach_gifs"))
async def tool_attach_gifs(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
    exercises: list[DayExercises],
) -> list[DayExercises]:
    """Attach GIF links to exercises if available."""
    tool_name = "tool_attach_gifs"
    deps, skipped, cached = _start_tool(ctx, tool_name)
    client_id = deps.client_id
    if skipped:
        cached_days = cast(list[DayExercises], cached if cached is not None else exercises)
        return cached_days
    if deps.max_run_seconds > 0:
        remaining_budget: float = deps.max_run_seconds - (monotonic() - deps.started_at)
        min_budget: float = float(settings.AI_COACH_ATTACH_GIFS_MIN_BUDGET)
        if remaining_budget < min_budget:
            logger.info(f"skip_attach_gifs client_id={client_id} reason=low_budget remaining={remaining_budget:.2f}")
            return _cache_result(deps, tool_name, exercises)
    try:
        gif_manager = get_gif_manager()
    except Exception as e:  # pragma: no cover - optional service
        logger.info(f"gif manager unavailable: {e}")
        return _cache_result(deps, tool_name, exercises)

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
    first_exercise = result[0].exercises[0].name if result and result[0].exercises else None
    logger.debug(f"tool_attach_gifs done client_id={client_id} first_name={first_exercise!r}")
    return _cache_result(deps, tool_name, result)


@toolset.tool(prepare=_single_use_prepare("tool_create_subscription"))
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

    tool_name = "tool_create_subscription"
    deps, skipped, cached = _start_tool(ctx, tool_name)
    if skipped:
        return cast(Subscription, cached)
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
            deps.final_result = sub
            return _cache_result(deps, tool_name, sub)
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
        subscription = Subscription.model_validate(data)
        deps.final_result = subscription
        return _cache_result(deps, tool_name, subscription)
    except ModelRetry:
        raise
    except Exception as e:  # pragma: no cover - forward to model
        raise ModelRetry(f"Subscription creation failed: {e}. Verify inputs and try again.") from e
