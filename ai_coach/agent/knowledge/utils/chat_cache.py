import asyncio
from typing import ClassVar, Sequence

from redis.asyncio import Redis

from ai_coach.types import MessageRole
from config.app_settings import settings


class _ChatRedisFactory:
    """Per-event-loop Redis clients for chat cache storage."""

    _clients: ClassVar[dict[int, Redis]] = {}

    @classmethod
    def get_client(cls) -> Redis:
        loop_id = id(asyncio.get_running_loop())
        client = cls._clients.get(loop_id)
        if client is None:
            client = Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                db=settings.AI_COACH_REDIS_CHAT_DB,
            )
            cls._clients[loop_id] = client
        return client


def _history_key(profile_id: int) -> str:
    return f"ai_coach:kb_chat:history:{profile_id}"


def _language_key(profile_id: int) -> str:
    return f"ai_coach:kb_chat:language:{profile_id}"


def _normalize_message(role: MessageRole, text: str) -> str:
    trimmed = str(text or "").strip()
    return f"{role.value}: {trimmed}" if trimmed else ""


async def append_message(profile_id: int, role: MessageRole, text: str, language: str | None) -> int:
    payload = _normalize_message(role, text)
    if not payload:
        return 0
    client = _ChatRedisFactory.get_client()
    length = await client.rpush(_history_key(profile_id), payload)
    if language:
        await client.set(_language_key(profile_id), language)
    return int(length or 0)


async def get_messages(profile_id: int) -> list[str]:
    client = _ChatRedisFactory.get_client()
    return list(await client.lrange(_history_key(profile_id), 0, -1))


async def get_recent_messages(profile_id: int, limit: int | None) -> list[str]:
    if limit is None or limit <= 0:
        return await get_messages(profile_id)
    client = _ChatRedisFactory.get_client()
    return list(await client.lrange(_history_key(profile_id), -limit, -1))


async def trim_messages(profile_id: int, processed_len: int) -> None:
    client = _ChatRedisFactory.get_client()
    if processed_len <= 0:
        return
    await client.ltrim(_history_key(profile_id), processed_len, -1)
    remaining = await client.llen(_history_key(profile_id))
    if remaining == 0:
        await client.delete(_language_key(profile_id))


async def clear_messages(profile_id: int) -> None:
    client = _ChatRedisFactory.get_client()
    await client.delete(_history_key(profile_id), _language_key(profile_id))


async def get_language(profile_id: int) -> str | None:
    client = _ChatRedisFactory.get_client()
    value = await client.get(_language_key(profile_id))
    if value is None:
        return None
    return str(value).strip() or None


def count_roles(messages: Sequence[str]) -> dict[MessageRole, int]:
    counts = {MessageRole.CLIENT: 0, MessageRole.AI_COACH: 0}
    for entry in messages:
        if entry.startswith(f"{MessageRole.CLIENT.value}:"):
            counts[MessageRole.CLIENT] += 1
        elif entry.startswith(f"{MessageRole.AI_COACH.value}:"):
            counts[MessageRole.AI_COACH] += 1
    return counts
