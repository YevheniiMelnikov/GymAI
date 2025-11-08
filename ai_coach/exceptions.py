"""Custom exceptions for the AI coach."""


class AgentExecutionAborted(RuntimeError):
    """Raised when an agent run must stop early."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class ProjectionProbeError(RuntimeError):
    """Raised when dataset readiness cannot be determined due to configuration issues."""

    pass
