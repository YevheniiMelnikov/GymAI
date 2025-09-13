from .base import AgentDeps, CoachAgentProtocol

__all__ = [
    "AgentDeps",
    "CoachAgentProtocol",
    "CoachAgent",
    "ProgramAdapter",
    "QAResponse",
]


from typing import Any


def __getattr__(name: str) -> Any:
    if name in {"CoachAgent", "ProgramAdapter", "QAResponse"}:
        from .coach import CoachAgent, ProgramAdapter, QAResponse  # type: ignore

        globals().update(
            {
                "CoachAgent": CoachAgent,
                "ProgramAdapter": ProgramAdapter,
                "QAResponse": QAResponse,
            }
        )
        return globals()[name]
    raise AttributeError(name)
