from dataclasses import dataclass
from typing import Protocol

from core.schemas import Program, QAResponse, Subscription
from core.enums import WorkoutType


@dataclass
class AgentDeps:
    client_id: int
    locale: str | None = None
    allow_save: bool = True
    client_name: str | None = None


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
        result_type: type[Program] | type[Subscription],
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
        result_type: type[Program] | type[Subscription] = Subscription,
    ) -> Program | Subscription: ...

    @classmethod
    async def answer_question(cls, prompt: str, deps: AgentDeps) -> QAResponse: ...
