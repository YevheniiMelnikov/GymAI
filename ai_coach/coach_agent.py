from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, Field, model_validator
from loguru import logger

from config.app_settings import settings
from core.schemas import DayExercises, Program, QAResponse, Subscription

try:  # pragma: no cover - optional dependency
    from pydantic_ai import Agent, RunContext
    from pydantic_ai.models.openai import OpenAIModel
except Exception:  # pragma: no cover - optional dependency
    Agent = None  # type: ignore[assignment]
    RunContext = Any  # type: ignore[assignment]
    OpenAIModel = None  # type: ignore[assignment]


SYSTEM_PROMPT_PATH = Path(__file__).with_name("prompts") / "coach_system_prompt.txt"


@dataclass
class AgentDeps:
    client_id: int
    locale: str | None = None
    allow_save: bool = True
    log_conversation_for_ask_ai: bool = False


class ProgramPayload(Program):
    """Program schema used by the agent (allows schema_version)."""

    schema_version: str | None = Field(
        default=None,
        description="Internal schema version used by the agent; dropped before save",
    )

    @model_validator(mode="after")
    def _validate_invariants(self) -> "ProgramPayload":
        if not self.exercises_by_day:
            raise ValueError("exercises_by_day must not be empty")
        for day in self.exercises_by_day:
            if not day.exercises:
                raise ValueError("day exercises must not be empty")
            for ex in day.exercises:
                if not (ex.name and ex.sets and ex.reps):
                    raise ValueError("exercise must have name, sets and reps")
        if self.split_number is None:
            self.split_number = len(self.exercises_by_day)
        return self


class SubscriptionPayload(BaseModel):
    """Subscription schema produced by the agent."""

    workout_days: list[str]
    exercises: list[DayExercises]
    wishes: str | None = None
    schema_version: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "SubscriptionPayload":
        if not self.workout_days:
            raise ValueError("workout_days must not be empty")
        if not self.exercises:
            raise ValueError("exercises must not be empty")
        return self


UpdatedProgramPayload = ProgramPayload


class ProgramAdapter:
    """Utility to convert agent payloads to API models."""

    @staticmethod
    def to_domain(payload: ProgramPayload) -> Program:
        data = payload.model_dump(exclude={"schema_version"})
        return Program.model_validate(data)


async def tool_get_client_context(ctx: RunContext[AgentDeps], query: str) -> dict[str, Sequence[str]]:
    """Return personal context for a client by query."""

    from ai_coach.cognee_coach import CogneeCoach

    client_id = ctx.deps.client_id
    logger.debug("tool_get_client_context client_id={} query={}", client_id, query)
    return await CogneeCoach.get_client_context(client_id, query)


async def tool_search_knowledge(ctx: RunContext[AgentDeps], query: str, k: int = 6) -> list[str]:
    """Search global knowledge base with top-k limit."""

    from ai_coach.cognee_coach import CogneeCoach

    logger.debug(
        "tool_search_knowledge query='{}' k={}",
        query[:80],
        k,
    )
    result = await CogneeCoach.search_knowledge(query, k)
    logger.debug("tool_search_knowledge results={}", len(result))
    return result


async def tool_save_program(ctx: RunContext[AgentDeps], plan: ProgramPayload) -> Program:
    """Persist generated plan for the current client."""

    from core.services import APIService

    if not ctx.deps.allow_save:
        raise RuntimeError("saving not allowed in this mode")
    client_id = ctx.deps.client_id
    logger.debug("tool_save_program client_id={}", client_id)
    program = ProgramAdapter.to_domain(plan)
    try:
        saved = await APIService.workout.save_program(
            client_profile_id=client_id,
            exercises=program.exercises_by_day,
            split_number=program.split_number or len(program.exercises_by_day),
            wishes=program.wishes or "",
        )
        logger.debug(
            "event=save_program.success program_id={} client_id={}",
            saved.id,
            client_id,
        )
        return saved
    except Exception as e:  # pragma: no cover - log and re-raise
        logger.error(f"Failed to save program for user {client_id}: {e}")
        raise


async def tool_get_program_history(ctx: RunContext[AgentDeps]) -> list[Program]:
    """Return client's previous programs."""

    from core.services import APIService

    client_id = ctx.deps.client_id
    logger.debug("tool_get_program_history client_id={}", client_id)
    return await APIService.workout.get_all_programs(client_id)


async def tool_attach_gifs(ctx: RunContext[AgentDeps], exercises: list[DayExercises]) -> list[DayExercises]:
    """Attach GIF links to exercises if available."""

    from core.resources.exercises import exercise_dict
    from core.services import get_gif_manager
    from core.utils.short_url import short_url
    from core.cache import Cache

    client_id = ctx.deps.client_id
    logger.debug("tool_attach_gifs client_id={}", client_id)
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
                    logger.debug("cache_gif_filename failed name={} err={}", ex.name, e)
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
    logger.debug(
        "tool_create_subscription client_id={} period={} days={}",
        client_id,
        period,
        workout_days,
    )
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
    logger.debug(
        "event=create_subscription.success subscription_id={} payment_date={}",
        sub_id,
        payment_date,
    )
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


class CoachAgent:
    """PydanticAI wrapper for program generation."""

    _agent: Any | None = None

    @classmethod
    def _get_agent(cls) -> Any:
        if Agent is None or OpenAIModel is None:
            raise RuntimeError("pydantic_ai package is required")
        if cls._agent is None:
            model = OpenAIModel(
                settings.LLM_MODEL,
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_API_URL,
                timeout=settings.AGENT_TIMEOUT,
            )
            cls._agent = Agent(
                model=model,
                deps_type=AgentDeps,
                tools=[
                    tool_get_client_context,
                    tool_search_knowledge,
                    tool_get_program_history,
                    tool_attach_gifs,
                    tool_save_program,
                    tool_create_subscription,
                ],
                result_type=ProgramPayload,
                retries=settings.AI_GENERATION_RETRIES,
            )

            @cls._agent.system_prompt
            async def coach_sys(ctx: RunContext[AgentDeps]) -> str:  # pragma: no cover - runtime config
                lang = ctx.deps.locale or settings.DEFAULT_LANG
                prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
                return prompt.format(locale=lang)

        return cls._agent

    @classmethod
    async def generate_program(cls, prompt: str, deps: AgentDeps) -> Program:
        agent = cls._get_agent()
        user_prompt = f"MODE: program\n{prompt}".strip()
        result: Program = await agent.run(user_prompt, deps=deps, result_type=Program)
        return result

    @classmethod
    async def generate_subscription(
        cls,
        prompt: str,
        period: str,
        workout_days: list[str],
        deps: AgentDeps,
        wishes: str | None = None,
    ) -> Subscription:
        agent = cls._get_agent()
        extra = (
            "\nMODE: subscription"
            + f"\nPeriod: {period}"
            + f"\nWorkout days: {', '.join(workout_days)}"
            + f"\nWishes: {wishes or ''}"
        )
        user_prompt = (prompt + extra).strip()
        result: Subscription = await agent.run(
            user_prompt,
            deps=deps,
            result_type=Subscription,
        )
        return result

    @classmethod
    async def update_program(cls, prompt: str, expected_workout: str, feedback: str, deps: AgentDeps) -> Program:
        agent = cls._get_agent()
        extra = "\nMODE: update" + f"\n--- Expected Workout ---\n{expected_workout}" + f"\n--- Feedback ---\n{feedback}"
        user_prompt = (prompt + extra).strip()
        result: Program = await agent.run(user_prompt, deps=deps, result_type=Program)
        return result

    @classmethod
    async def answer_question(cls, prompt: str, deps: AgentDeps) -> QAResponse:
        agent = cls._get_agent()
        user_prompt = f"MODE: ask_ai\n{prompt}"
        result: QAResponse = await agent.run(
            user_prompt,
            deps=deps,
            result_type=QAResponse,
            temperature=0.3,
            max_output_tokens=256,
        )
        return result
