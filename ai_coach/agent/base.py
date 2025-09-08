from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.schemas import Program, QAResponse, Subscription


@dataclass
class AgentDeps:
    client_id: int
    locale: str | None = None
    allow_save: bool = True
    client_name: str | None = None


class CoachAgentProtocol(Protocol):
    @classmethod
    async def generate_program(cls, prompt: str, deps: AgentDeps) -> Program: ...

    @classmethod
    async def generate_subscription(
        cls,
        prompt: str,
        period: str,
        workout_days: list[str],
        deps: AgentDeps,
        wishes: str | None = None,
    ) -> Subscription: ...

    @classmethod
    async def update_program(
        cls,
        prompt: str,
        expected_workout: str,
        feedback: str,
        deps: AgentDeps,
    ) -> Program: ...

    @classmethod
    async def answer_question(cls, prompt: str, deps: AgentDeps) -> QAResponse: ...
