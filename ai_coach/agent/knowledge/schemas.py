from enum import Enum
from dataclasses import dataclass
from typing import Any, Mapping, Literal


class ProjectionStatus(Enum):
    READY = "ready"
    READY_EMPTY = "ready_empty"
    TIMEOUT = "timeout"
    FATAL_ERROR = "fatal_error"
    USER_CONTEXT_UNAVAILABLE = "user_context_unavailable"


@dataclass(slots=True)
class KnowledgeSnippet:
    text: str
    dataset: str | None = None
    kind: Literal["document", "message", "note", "unknown"] = "document"

    def is_content(self) -> bool:
        return self.kind in {"document", "note"}


@dataclass(slots=True)
class DatasetRow:
    text: str
    metadata: Mapping[str, Any] | None = None


@dataclass(slots=True)
class RebuildResult:
    reinserted: int = 0
    healed_documents: int = 0
    linked: int = 0
    rehydrated: int = 0
    last_dataset: str | None = None
    healed: bool = True
    reason: str | None = None
