from dataclasses import dataclass

from core.schemas import Profile


@dataclass(slots=True)
class AskAiPreparationResult:
    profile: Profile
    prompt: str
    cost: int
    image_base64: str | None
    image_mime: str | None
