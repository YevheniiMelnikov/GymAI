from __future__ import annotations

from core.services import APIService
from core.schemas import QAResponse


async def ask_ai(profile_id: int, question: str, *, language: str | None) -> QAResponse:
    response = await APIService.ai_coach.ask(
        prompt=question,
        profile_id=profile_id,
        language=language,
    )
    if response is None:
        raise RuntimeError("ask_ai_empty_response")
    return response
