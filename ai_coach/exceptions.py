"""Custom exceptions for the AI coach."""


class AgentExecutionAborted(RuntimeError):
    """Raised when an agent run must stop early."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class ProjectionProbeError(RuntimeError):
    """Raised when dataset readiness cannot be determined due to configuration issues."""

    pass


class KnowledgeBaseUnavailableError(RuntimeError):
    """Raised when knowledge base dependencies are unavailable or unhealthy."""

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason or "knowledge_base_unavailable"
