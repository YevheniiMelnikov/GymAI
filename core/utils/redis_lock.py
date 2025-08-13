from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import ClassVar, Dict, AsyncIterator, Awaitable, cast
from uuid import uuid4

from redis.asyncio import Redis
from redis.asyncio.client import Pipeline  # for typing

from config.app_settings import settings


class _RedisFactory:
    """Per-event-loop Redis clients to avoid cross-loop issues."""

    _clients: ClassVar[Dict[int, Redis]] = {}

    @classmethod
    def get_client(cls) -> Redis:
        loop_id = id(asyncio.get_running_loop())
        client = cls._clients.get(loop_id)
        if client is None:
            client = Redis.from_url(settings.REDIS_URL, decode_responses=True)  # str payloads
            cls._clients[loop_id] = client
        return client

    @classmethod
    async def aclose_all(cls) -> None:
        for k, c in list(cls._clients.items()):
            try:
                await c.aclose()  # pyrefly: ignore[missing-attribute]
            finally:
                cls._clients.pop(k, None)


_RELEASE_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class RedisLock:
    """
    Simple Redis distributed lock with TTL and safe release:
    - acquire: SET key token NX PX ttl_ms
    - release: Lua compare-and-del
    """

    def __init__(self, key: str, ttl_ms: int) -> None:
        self.key = key
        self.ttl_ms = ttl_ms
        self.token = uuid4().hex
        self._client: Redis = _RedisFactory.get_client()
        self._held = False

    async def acquire(self) -> bool:
        ok = await self._client.set(self.key, self.token, nx=True, px=self.ttl_ms)
        self._held = bool(ok)
        return self._held

    async def refresh(self) -> bool:
        if not self._held:
            return False
        # best-effort: extend TTL only if still owner
        pipe: Pipeline = self._client.pipeline()
        await pipe.watch(self.key)
        cur = await self._client.get(self.key)
        if cur != self.token:
            await pipe.reset()
            self._held = False
            return False
        pipe.multi()
        pipe.pexpire(self.key, self.ttl_ms)
        result = False
        try:
            res = await pipe.execute()
            result = bool(res and res[-1])
        finally:
            await pipe.reset()
        return result

    async def release(self) -> None:
        if not self._held:
            return
        try:
            await cast(Awaitable[int], self._client.eval(_RELEASE_LUA, 1, self.key, self.token))
        finally:
            self._held = False


@asynccontextmanager
async def redis_try_lock(
    key: str,
    *,
    ttl_ms: int = 180_000,
    wait: bool = False,
    wait_timeout: float = 2.0,
    retry_interval: float = 0.2,
) -> AsyncIterator[bool]:
    """
    Try to acquire a distributed lock.
    - wait=False: single attempt (non-blocking).
    - wait=True: spin-wait up to wait_timeout with retry_interval.
    Returns True if lock acquired.
    """
    lock = RedisLock(key, ttl_ms)
    acquired = await lock.acquire()
    if not acquired and wait:
        deadline = asyncio.get_running_loop().time() + wait_timeout
        while not acquired and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(retry_interval)
            acquired = await lock.acquire()

    try:
        yield acquired
    finally:
        if acquired:
            await lock.release()


def get_redis_client() -> Redis:
    return _RedisFactory.get_client()
