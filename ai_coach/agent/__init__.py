from typing import Any

from core.schemas import QAResponse

from .base import AgentDeps, CoachAgentProtocol
from .coach import CoachAgent
from .utils import ProgramAdapter

__all__ = ["AgentDeps", "CoachAgentProtocol", "CoachAgent", "ProgramAdapter", "QAResponse"]


def __getattr__(name: str) -> Any:
    # Retained for backward compatibility with older import patterns.
    if name in {"CoachAgent", "QAResponse"}:
        return globals()[name]
    if name == "ProgramAdapter":
        return globals()[name]
    raise AttributeError(name)
