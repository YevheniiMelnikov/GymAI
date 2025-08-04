from enum import Enum


class DataKind(str, Enum):
    """Types of data stored for each client."""

    MESSAGE = "message"
    PROMPT = "prompt"
