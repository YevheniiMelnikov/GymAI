from typing import Any

from core.ai.services import CogneeService


async def ai_coach_request(*args: Any, **kwargs: Any) -> None:
    """Forward a text prompt to the AI coach service."""
    text = kwargs.get("text")
    if not text and args:
        text = args[0]
    if not text:
        return
    await CogneeService.coach_request(str(text))


async def ai_coach_assign(*args: Any, **kwargs: Any) -> None:
    """Notify the AI coach service about client assignment."""
    client = kwargs.get("client")
    if client is None and args:
        client = args[0]
    if client is None:
        return
    await CogneeService.coach_assign(client)
