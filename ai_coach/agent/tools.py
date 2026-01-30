from asyncio import TimeoutError, wait_for
from datetime import datetime
from inspect import signature
import json
from time import monotonic
from typing import Any, Callable, Coroutine, TypeVar, TypedDict, cast
from zoneinfo import ZoneInfo

from loguru import logger
from pydantic_ai import ModelRetry, RunContext  # pyrefly: ignore[import-error]
from pydantic_ai.tools import ToolDefinition  # pyrefly: ignore[import-error]
from pydantic_ai.toolsets.function import FunctionToolset  # pyrefly: ignore[import-error]

from core.schemas import DayExercises, Program, Subscription
from core.enums import SubscriptionPeriod
from config.app_settings import settings

from .base import AgentDeps
from ai_coach.exceptions import AgentExecutionAborted
from ai_coach.types import CoachMode

from ..schemas import ProgramPayload
from ai_coach.agent.knowledge.knowledge_base import KnowledgeBase
from ai_coach.exceptions import KnowledgeBaseUnavailableError
from core.ai_coach.exercise_catalog import (
    EQUIPMENT_TYPES,
    EXERCISE_CATEGORIES,
    MUSCLE_GROUPS,
    load_exercise_catalog,
    search_exercises,
)
from ai_coach.agent.utils import ProgramAdapter, ensure_catalog_gif_keys, fill_missing_gif_keys
from ai_coach.agent import utils as agent_utils


def get_knowledge_base() -> KnowledgeBase:
    return agent_utils.get_knowledge_base()


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


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    text_attr = getattr(value, "text", None)
    if text_attr is not None:
        return str(text_attr or "").strip()
    return str(value).strip()


def _needs_instance_argument(func: Callable[..., Any]) -> bool:
    try:
        sig = signature(func)
    except (ValueError, TypeError):
        return True
    params = list(sig.parameters.values())
    if not params:
        return False
    first = params[0]
    return first.name in {"self", "cls"}


def _looks_like_prompt(query: str) -> bool:
    lowered = query.lower()
    if "mode:" in lowered:
        return True
    if "you are an ai coach" in lowered:
        return True
    return False


def _raise_tool_limit(deps: AgentDeps, tool_name: str) -> None:
    mode_value = deps.mode.value if deps.mode else "unknown"
    message = ("agent_tool_limit_exceeded profile_id={profile_id} tool={tool} steps={steps} mode={mode}").format(
        profile_id=deps.profile_id,
        tool=tool_name,
        steps=deps.tool_calls,
        mode=mode_value,
    )
    logger.info(message)
    raise AgentExecutionAborted("AI coach tool budget exhausted", reason="max_tool_calls_exceeded")


def _prepare_tool(ctx: RunContext[AgentDeps], tool_name: str) -> AgentDeps:  # pyrefly: ignore[unsupported-operation]
    deps = ctx.deps
    elapsed = monotonic() - deps.started_at
    if deps.max_run_seconds > 0 and elapsed > deps.max_run_seconds:
        mode_value = deps.mode.value if deps.mode else "unknown"
        logger.info(
            f"agent_tool_timeout profile_id={deps.profile_id} tool={tool_name} elapsed={elapsed:.2f} mode={mode_value}"
        )
        raise AgentExecutionAborted("AI coach request timed out", reason="timeout")
    deps.tool_calls += 1
    if deps.max_tool_calls > 0 and deps.tool_calls > deps.max_tool_calls:
        _raise_tool_limit(deps, tool_name)
    deps.tool_call_counts[tool_name] = deps.tool_call_counts.get(tool_name, 0) + 1
    return deps


def _log_tool_disabled(deps: AgentDeps, tool_name: str, *, reason: str) -> None:
    if tool_name in deps.disabled_tools:
        return
    deps.disabled_tools.add(tool_name)


def _start_tool(
    ctx: RunContext[AgentDeps], tool_name: str, *, cache_key: tuple[str, ...] | None = None
) -> tuple[AgentDeps, bool, Any]:  # pyrefly: ignore[unsupported-operation]
    deps = ctx.deps
    normalized_key = tuple(cache_key or (tool_name,))
    cached = deps.tool_cache.get(normalized_key)
    if normalized_key in deps.tool_call_keys:
        _log_tool_disabled(deps, tool_name, reason="tool_repeat_skipped")
        return deps, True, cached
    prepared = _prepare_tool(ctx, tool_name)
    prepared.called_tools.add(tool_name)
    prepared.tool_call_keys.add(normalized_key)
    return prepared, False, cached


def _cache_result(deps: AgentDeps, tool_name: str, result: T, *, cache_key: tuple[str, ...] | None = None) -> T:
    normalized_key = tuple(cache_key or (tool_name,))
    deps.tool_cache[normalized_key] = result
    return result


def _single_use_prepare(
    tool_name: str,
) -> Callable[[RunContext[AgentDeps], ToolDefinition], Coroutine[Any, Any, ToolDefinition | None]]:
    async def _prepare(
        ctx: RunContext[AgentDeps], tool_def: ToolDefinition
    ) -> ToolDefinition | None:  # pyrefly: ignore[unsupported-operation]
        deps = ctx.deps
        if tool_name in deps.disabled_tools:
            _log_tool_disabled(deps, tool_name, reason="tool_disabled_explicitly")
            return None
        allowed_modes = TOOL_ALLOWED_MODES.get(tool_name)
        mode = deps.mode
        if allowed_modes is not None and mode is not None and mode not in allowed_modes:
            _log_tool_disabled(deps, tool_name, reason="tool_disabled_for_mode")
            return None
        if tool_name == "tool_search_exercises" and mode in (
            CoachMode.program,
            CoachMode.subscription,
            CoachMode.update,
        ):
            max_calls = int(settings.AI_COACH_MAX_EXERCISE_SEARCH_CALLS)
            current_calls = deps.tool_call_counts.get(tool_name, 0)
            if max_calls <= 0 or current_calls >= max_calls:
                _log_tool_disabled(deps, tool_name, reason="tool_disabled_after_limit")
                return None
            return tool_def
        if mode in (CoachMode.program, CoachMode.subscription, CoachMode.update) and tool_name in deps.called_tools:
            _log_tool_disabled(deps, tool_name, reason="tool_disabled_after_first_call")
            return None
        return tool_def

    return _prepare


def _normalize_exercise_day_labels(exercises: list[DayExercises]) -> list[str]:
    normalized: list[str] = []
    for idx, day in enumerate(exercises):
        label = f"Day {idx + 1}"
        day.day = label
        normalized.append(label)
    if not normalized:
        normalized.append("Day 1")
    return normalized


class ExerciseCatalogItem(TypedDict):
    gif_key: str
    canonical: str
    aliases: list[str]
    category: str
    primary_muscles: list[str]
    secondary_muscles: list[str]
    equipment: list[str]


class BMIResult(TypedDict):
    bmi: float
    weight_kg: float
    height_cm: float


@toolset.tool(prepare=_single_use_prepare("tool_search_exercises"))  # pyrefly: ignore[no-matching-overload]
async def tool_search_exercises(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
    *,
    category: str | None,
    primary_muscles: list[str] | None,
    secondary_muscles: list[str] | None,
    equipment: list[str] | None,
    limit: int | None,
) -> list[ExerciseCatalogItem]:
    """Search the exercise catalog by category, muscle groups, and equipment."""
    tool_name = "tool_search_exercises"
    normalized_category = str(category or "strength").strip().lower()
    if normalized_category not in EXERCISE_CATEGORIES:
        raise ModelRetry("Invalid category. Use one of: strength, conditioning, health.")
    primary = [item.strip().lower() for item in (primary_muscles or []) if str(item or "").strip()]
    secondary = [item.strip().lower() for item in (secondary_muscles or []) if str(item or "").strip()]
    equipment_list = [item.strip().lower() for item in (equipment or []) if str(item or "").strip()]
    if len(primary) > 1:
        raise ModelRetry("Provide at most one primary muscle group per search.")
    if secondary:
        raise ModelRetry("Do not pass secondary muscles. Use only one primary muscle group or leave it empty.")
    if len(equipment_list) > 1:
        raise ModelRetry("Provide at most one equipment type per search or omit the equipment filter.")
    if normalized_category in {"conditioning", "health"}:
        primary = []
        secondary = []
        equipment_list = []
    category = normalized_category
    primary_muscles = primary or None
    secondary_muscles = None
    equipment = equipment_list or None

    if limit is None:
        effective_limit = int(settings.AI_COACH_EXERCISE_SEARCH_LIMIT)
    else:
        effective_limit = max(1, int(limit))
    cache_key = (
        tool_name,
        str(category or ""),
        ",".join(primary_muscles or []),
        ",".join(secondary_muscles or []),
        ",".join(equipment or []),
    )
    deps, skipped, cached = _start_tool(ctx, tool_name, cache_key=cache_key)
    if skipped:
        return cast(list[ExerciseCatalogItem], cached if cached is not None else [])
    entries = load_exercise_catalog()
    if not entries:
        raise AgentExecutionAborted("Exercise catalog is missing", reason="exercise_catalog_missing")
    logger.debug(
        "tool_search_exercises profile_id={} category={} primary={} secondary={} limit={}",
        deps.profile_id,
        category,
        primary_muscles,
        secondary_muscles,
        effective_limit,
    )
    results = search_exercises(
        category=category,
        primary_muscles=primary_muscles,
        secondary_muscles=secondary_muscles,
        equipment=equipment,
        limit=effective_limit,
    )
    if not results:
        fallback = search_exercises(limit=effective_limit)
        if fallback:
            logger.info(
                "tool_search_exercises_fallback profile_id={} reason=empty_results fallback_count={}",
                deps.profile_id,
                len(fallback),
            )
            results = fallback
    logger.info(
        "tool_search_exercises_result profile_id={} count={}",
        deps.profile_id,
        len(results),
    )
    payload: list[ExerciseCatalogItem] = [
        {
            "gif_key": entry.gif_key,
            "canonical": entry.canonical,
            "aliases": list(entry.aliases),
            "category": entry.category,
            "primary_muscles": list(entry.primary_muscles),
            "secondary_muscles": list(entry.secondary_muscles),
            "equipment": list(entry.equipment),
        }
        for entry in results
    ]
    if category and str(category).lower() not in EXERCISE_CATEGORIES:
        _log_tool_disabled(deps, tool_name, reason="invalid_category")
    if primary:
        invalid_primary = {item.lower() for item in primary} - MUSCLE_GROUPS
        if invalid_primary:
            _log_tool_disabled(deps, tool_name, reason="invalid_primary_muscles")
    if equipment_list:
        invalid_equipment = {item.lower() for item in equipment_list} - EQUIPMENT_TYPES
        if invalid_equipment:
            _log_tool_disabled(deps, tool_name, reason="invalid_equipment")
    return _cache_result(deps, tool_name, payload, cache_key=cache_key)


@toolset.tool()  # pyrefly: ignore[no-matching-overload]
async def tool_calculate_bmi(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
    *,
    weight_kg: float,
    height_cm: float,
) -> BMIResult:
    """Calculate BMI from weight (kg) and height (cm)."""
    tool_name = "tool_calculate_bmi"
    cache_key = (tool_name, f"{weight_kg:.3f}", f"{height_cm:.3f}")
    deps, skipped, cached = _start_tool(ctx, tool_name, cache_key=cache_key)
    if skipped:
        if cached is not None:
            return cast(BMIResult, cached)
    if weight_kg <= 0 or height_cm <= 0:
        raise ModelRetry("BMI calculation requires positive weight_kg and height_cm values.")
    height_m = height_cm / 100.0
    bmi_value = weight_kg / (height_m * height_m)
    result: BMIResult = {
        "bmi": round(bmi_value, 1),
        "weight_kg": round(weight_kg, 2),
        "height_cm": round(height_cm, 1),
    }
    logger.debug(
        "tool_calculate_bmi profile_id={} weight_kg={} height_cm={} bmi={}",
        deps.profile_id,
        weight_kg,
        height_cm,
        result["bmi"],
    )
    return _cache_result(deps, tool_name, result, cache_key=cache_key)


@toolset.tool(prepare=_single_use_prepare("tool_search_knowledge"))  # pyrefly: ignore[no-matching-overload]
async def tool_search_knowledge(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
    query: str,
    k: int | None = None,
) -> list[str]:
    """Search client and global knowledge with top-k limit."""
    kb = get_knowledge_base()

    tool_name = "tool_search_knowledge"
    normalized_query = query.strip()
    effective_k = 6 if k is None else int(k)
    cache_key = (tool_name, normalized_query, str(effective_k))
    deps, skipped, cached = _start_tool(ctx, tool_name, cache_key=cache_key)
    timeout = _tool_timeout("tool_search_knowledge")
    profile_id = deps.profile_id
    if deps.mode in {CoachMode.diet, CoachMode.program, CoachMode.subscription, CoachMode.update}:
        cap = float(settings.AI_COACH_GENERATION_SEARCH_TIMEOUT)
        if cap > 0:
            timeout = min(timeout, cap)
    logger.debug(f"tool_search_knowledge profile_id={profile_id} query='{normalized_query[:80]}' k={effective_k}")
    if skipped:
        cached_result = cast(list[str], cached if cached is not None else [])
        return cached_result
    if not normalized_query:
        raise ModelRetry("Knowledge search requires a non-empty query. Summarize the client's goal before retrying.")
    if _looks_like_prompt(normalized_query):
        deps.knowledge_base_empty = True
        deps.last_knowledge_query = normalized_query
        deps.last_knowledge_empty = True
        deps.kb_used = False
        logger.debug(
            f"knowledge_search_skipped profile_id={profile_id} query='{normalized_query[:80]}' reason=prompt_guard"
        )
        return _cache_result(deps, tool_name, [], cache_key=cache_key)
    if deps.knowledge_base_empty:
        deps.last_knowledge_query = normalized_query
        deps.last_knowledge_empty = True
        deps.kb_used = False
        logger.info(
            f"knowledge_search_aborted profile_id={profile_id} "
            f"query='{normalized_query[:80]}' reason=knowledge_base_empty"
        )
        raise AgentExecutionAborted("knowledge_base_empty", reason="knowledge_base_empty")
    if deps.last_knowledge_query == normalized_query and deps.last_knowledge_empty:
        logger.debug(
            f"knowledge_search_repeat profile_id={profile_id} query='{normalized_query[:80]}' reason=empty_previous"
        )
        deps.kb_used = False
        return _cache_result(deps, tool_name, [], cache_key=cache_key)

    snippets: list[Any] = []
    try:
        snippets = await wait_for(
            kb.search(
                normalized_query,
                profile_id,
                effective_k,
                request_id=deps.request_rid,
            ),
            timeout=timeout,
        )
    except AgentExecutionAborted:
        raise
    except TimeoutError:
        logger.info(
            f"knowledge_search_timeout profile_id={profile_id} query='{normalized_query[:80]}' timeout={timeout:.1f}"
        )
        deps.last_knowledge_query = normalized_query
        deps.last_knowledge_empty = False
        deps.knowledge_base_empty = False
        deps.kb_used = False
        raise AgentExecutionAborted("knowledge_base_unavailable", reason="knowledge_base_unavailable")
    except KnowledgeBaseUnavailableError as exc:
        logger.warning(
            f"knowledge_search_failed profile_id={profile_id} query='{normalized_query[:80]}' "
            f"reason={exc.reason} detail={exc}"
        )
        deps.last_knowledge_query = normalized_query
        deps.last_knowledge_empty = False
        deps.knowledge_base_empty = False
        deps.kb_used = False
        reason = exc.reason or "knowledge_base_unavailable"
        raise AgentExecutionAborted(reason, reason=reason) from exc
    except Exception as e:
        logger.warning(f"knowledge_search_failed profile_id={profile_id} query='{normalized_query[:80]}' detail={e}")
        deps.last_knowledge_query = normalized_query
        deps.last_knowledge_empty = False
        deps.knowledge_base_empty = False
        deps.kb_used = False
        raise AgentExecutionAborted("knowledge_base_unavailable", reason="knowledge_base_unavailable") from e

    deps.last_knowledge_query = normalized_query
    if snippets:
        deps.last_knowledge_empty = False
        deps.knowledge_base_empty = False
        deps.kb_used = True
        logger.debug(f"tool_search_knowledge results={len(snippets)}")
        texts = [text for text in (_as_text(snippet) for snippet in snippets) if text]
        if texts:
            return _cache_result(deps, tool_name, texts, cache_key=cache_key)

    deps.last_knowledge_query = normalized_query
    deps.last_knowledge_empty = True
    deps.knowledge_base_empty = True
    deps.kb_used = False
    logger.info(f"knowledge_search_empty profile_id={profile_id} query='{normalized_query[:80]}' detail=no_entries")
    raise AgentExecutionAborted("knowledge_base_empty", reason="knowledge_base_empty")


@toolset.tool(prepare=_single_use_prepare("tool_get_chat_history"))  # pyrefly: ignore[no-matching-overload]
async def tool_get_chat_history(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
    limit: int | None = None,
) -> list[str]:
    """Load recent chat messages for context."""
    kb = get_knowledge_base()
    tool_name = "tool_get_chat_history"
    effective_limit = 20 if limit is None else int(limit)
    cache_key = (tool_name, str(effective_limit))
    deps, skipped, cached = _start_tool(ctx, tool_name, cache_key=cache_key)
    timeout = _tool_timeout("tool_get_chat_history")
    profile_id = deps.profile_id
    logger.debug(f"tool_get_chat_history profile_id={profile_id} limit={effective_limit}")
    if skipped:
        cached_history = cast(list[str], cached if cached is not None else [])
        limited = list(cached_history[:effective_limit])
        return limited

    history = deps.cached_history
    if history is None:
        try:
            history = await wait_for(kb.get_message_history(profile_id, effective_limit), timeout=timeout)
        except TimeoutError:
            logger.info(f"chat_history_timeout profile_id={profile_id} tool=tool_get_chat_history timeout={timeout}")
            history = []
        except Exception as exc:
            logger.error(f"Error getting chat history: {exc}")
            raise
        deps.cached_history = history

    limited = list(history[:effective_limit])
    return _cache_result(deps, tool_name, limited, cache_key=cache_key)


@toolset.tool(prepare=_single_use_prepare("tool_save_program"))  # pyrefly: ignore[no-matching-overload]
async def tool_save_program(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
    plan_json: str,
) -> Program:
    """Persist generated plan for the current client."""
    from core.services import APIService

    tool_name = "tool_save_program"
    deps, skipped, cached = _start_tool(ctx, tool_name)
    if skipped:
        return cast(Program, cached)
    if not deps.allow_save:
        raise RuntimeError("saving not allowed in this mode")
    profile_id = deps.profile_id
    logger.debug(f"tool_save_program profile_id={profile_id}")
    try:
        raw_payload = json.loads(plan_json)
    except json.JSONDecodeError as exc:
        raise ModelRetry(f"Program payload must be valid JSON: {exc}") from exc
    if not isinstance(raw_payload, dict):
        raise ModelRetry("Program payload must be a JSON object.")
    program_payload = ProgramPayload.model_validate(raw_payload)
    program = ProgramAdapter.to_domain(program_payload)
    timeout: float = float(settings.AI_COACH_SAVE_TIMEOUT)
    try:
        saved = await wait_for(
            APIService.workout.save_program(
                profile_id=profile_id,
                exercises=program.exercises_by_day,
                split_number=program.split_number or len(program.exercises_by_day),
                wishes=program.wishes or "",
            ),
            timeout=timeout,
        )
        logger.debug(f"event=save_program.success program_id={saved.id} profile_id={profile_id}")
        deps.final_result = saved
        return _cache_result(deps, tool_name, saved)
    except TimeoutError:
        logger.info(f"save_program_timeout profile_id={profile_id} timeout={timeout}")
        deps.final_result = program
        return _cache_result(deps, tool_name, program)
    except Exception as e:
        raise ModelRetry(f"Program saving failed: {e}. Ensure plan data is valid and retry.") from e


@toolset.tool(prepare=_single_use_prepare("tool_get_program_history"))  # pyrefly: ignore[no-matching-overload]
async def tool_get_program_history(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
) -> list[Program]:
    """Return client's previous programs."""
    from core.services import APIService

    tool_name = "tool_get_program_history"
    deps, skipped, cached = _start_tool(ctx, tool_name)
    timeout = _tool_timeout("tool_get_program_history")
    profile_id = deps.profile_id
    logger.debug(f"tool_get_program_history profile_id={profile_id}")
    if skipped:
        cached_result = cast(list[Program], cached if cached is not None else [])
        return cached_result
    try:
        history = await wait_for(APIService.workout.get_all_programs(profile_id), timeout=timeout)
        sorted_history = sorted(
            history,
            key=lambda program: float(getattr(program, "created_at", 0.0) or 0.0),
            reverse=True,
        )
        return _cache_result(deps, tool_name, sorted_history[:3])
    except TimeoutError:
        logger.info(f"program_history_timeout profile_id={profile_id} tool=tool_get_program_history timeout={timeout}")
        return _cache_result(deps, tool_name, [])
    except Exception as e:
        raise ModelRetry(f"Program history unavailable: {e}. Try calling the tool again later.") from e


@toolset.tool(prepare=_single_use_prepare("tool_create_subscription"))  # pyrefly: ignore[no-matching-overload]
async def tool_create_subscription(
    ctx: RunContext[AgentDeps],  # pyrefly: ignore[unsupported-operation]
    split_number: int,
    exercises: list[dict[str, object]],
    period: SubscriptionPeriod | None,
    wishes: str | None,
) -> Subscription:
    """Create a subscription and return its summary."""
    from decimal import Decimal

    from core.services import APIService
    from config.app_settings import settings

    tool_name = "tool_create_subscription"
    deps, skipped, cached = _start_tool(ctx, tool_name)
    if skipped:
        return cast(Subscription, cached)
    if not deps.allow_save:
        raise RuntimeError("saving not allowed in this mode")
    profile_id = deps.profile_id
    profile = await APIService.profile.get_profile(profile_id)
    workout_location = profile.workout_location if profile and profile.workout_location else None
    if not workout_location:
        raise ModelRetry("Workout location is required to create a subscription.")
    day_models = [DayExercises.model_validate(day) for day in exercises]
    normalized_days = _normalize_exercise_day_labels(day_models)
    normalized_split = max(1, min(7, int(split_number)))
    normalized_period = period or SubscriptionPeriod.one_month
    logger.debug(
        f"tool_create_subscription profile_id={profile_id} period={normalized_period} "
        f"split_number={normalized_split} days={normalized_days}"
    )
    exercises_payload = [d.model_dump() for d in day_models]
    fill_missing_gif_keys(exercises_payload)
    ensure_catalog_gif_keys(exercises_payload)
    price_map = {
        SubscriptionPeriod.one_month: int(settings.SMALL_SUBSCRIPTION_PRICE),
        SubscriptionPeriod.six_months: int(settings.MEDIUM_SUBSCRIPTION_PRICE),
        SubscriptionPeriod.twelve_months: int(settings.LARGE_SUBSCRIPTION_PRICE),
    }
    price = price_map.get(normalized_period, int(settings.SMALL_SUBSCRIPTION_PRICE))
    try:
        sub_id = await APIService.workout.create_subscription(
            profile_id=profile_id,
            split_number=normalized_split,
            wishes=wishes or "",
            amount=Decimal(price),
            period=normalized_period,
            workout_location=workout_location,
            exercises=exercises_payload,
        )
        if sub_id is None:
            raise ModelRetry("Subscription creation failed. Adjust provided data and retry.")
        logger.debug(f"event=create_subscription.success subscription_id={sub_id}")
        sub = await APIService.workout.get_latest_subscription(profile_id)
        if sub is not None:
            deps.final_result = sub
            return _cache_result(deps, tool_name, sub)
        data = {
            "id": sub_id,
            "profile": profile_id,
            "enabled": False,
            "price": price,
            "workout_location": workout_location,
            "wishes": wishes or "",
            "period": normalized_period.value,
            "split_number": normalized_split,
            "exercises": exercises_payload,
            "payment_date": datetime.now(ZoneInfo(settings.TIME_ZONE)).date().isoformat(),
        }
        subscription = Subscription.model_validate(data)
        deps.final_result = subscription
        return _cache_result(deps, tool_name, subscription)
    except ModelRetry:
        raise
    except Exception as e:
        raise ModelRetry(f"Subscription creation failed: {e}. Verify inputs and try again.") from e
