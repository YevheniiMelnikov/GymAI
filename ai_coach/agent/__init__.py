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
        try:
            from .coach import CoachAgent, ProgramAdapter, QAResponse  # type: ignore
        except Exception:  # pragma: no cover - fallback for missing deps
            from .coach_stub import CoachAgent, ProgramAdapter, QAResponse  # type: ignore

        globals().update(
            {
                "CoachAgent": CoachAgent,
                "ProgramAdapter": ProgramAdapter,
                "QAResponse": QAResponse,
            }
        )
        return globals()[name]
    raise AttributeError(name)
