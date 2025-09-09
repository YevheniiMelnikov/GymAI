import asyncio
from collections import OrderedDict


class LockCache:
    """LRU cache for asyncio locks to prevent unbounded growth."""

    def __init__(self, maxsize: int = 1000) -> None:
        self._locks: OrderedDict[str, asyncio.Lock] = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str) -> asyncio.Lock:
        if key in self._locks:
            self._locks.move_to_end(key)
        else:
            self._locks[key] = asyncio.Lock()
            if len(self._locks) > self._maxsize:
                self._locks.popitem(last=False)
        return self._locks[key]
