from dataclasses import dataclass

from core.schemas import Client


@dataclass(slots=True)
class AskAiPreparationResult:
    client: Client
    prompt: str
    cost: int
    image_base64: str | None
    image_mime: str | None
