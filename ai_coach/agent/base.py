from dataclasses import dataclass, field
from typing import Any, Protocol
from time import monotonic

from core.schemas import Program, Subscription
from core.schemas.qa import QAResponse
from core.enums import WorkoutType
from ai_coach.types import CoachMode
from config.app_settings import settings


@dataclass
class AgentDeps:
    client_id: int
    locale: str | None = None
    allow_save: bool = True
    client_name: str | None = None
    mode: CoachMode | None = None
    last_knowledge_query: str | None = None
    last_knowledge_empty: bool = False
    max_tool_calls: int = settings.AI_COACH_MAX_TOOL_CALLS
    max_run_seconds: float = float(settings.AI_COACH_REQUEST_TIMEOUT)
    tool_calls: int = 0
    knowledge_base_empty: bool = False
    fallback_used: bool = False
    cached_history: list[str] | None = None
    started_at: float = field(default_factory=monotonic)
    called_tools: set[str] = field(default_factory=set)
    tool_cache: dict[str, Any] = field(default_factory=dict)
    final_result: Program | Subscription | None = None
    disabled_tools: set[str] = field(default_factory=set)


class CoachAgentProtocol(Protocol):
    @classmethod
    async def generate_workout_plan(
        cls,
        prompt: str | None,
        deps: AgentDeps,
        *,
        workout_type: WorkoutType | None = None,
        period: str | None = None,
        workout_days: list[str] | None = None,
        wishes: str | None = None,
        output_type: type[Program] | type[Subscription],
        instructions: str | None = None,
    ) -> Program | Subscription: ...

    @classmethod
    async def update_workout_plan(
        cls,
        prompt: str | None,
        expected_workout: str,
        feedback: str,
        deps: AgentDeps,
        *,
        workout_type: WorkoutType | None = None,
        output_type: type[Program] | type[Subscription] = Subscription,
        instructions: str | None = None,
    ) -> Program | Subscription: ...

    @classmethod
    async def answer_question(cls, prompt: str, deps: AgentDeps) -> QAResponse: ...
