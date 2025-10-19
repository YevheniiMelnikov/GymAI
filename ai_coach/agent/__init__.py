from importlib import import_module
from typing import Any

from .base import AgentDeps, CoachAgentProtocol

__all__ = ["AgentDeps", "CoachAgentProtocol", "CoachAgent", "ProgramAdapter", "QAResponse"]


def __getattr__(name: str) -> Any:  # pragma: no cover - simple lazy import
    if name in {"CoachAgent", "ProgramAdapter", "QAResponse"}:
        module = import_module(".coach", __name__)
        return getattr(module, name)
    raise AttributeError(name)
