import time

from django.core.cache import cache


def acquire_once(key: str, ttl: int = 30) -> bool:
    now = int(time.time())
    added = cache.add(f"idemp:{key}", now, ttl)
    return bool(added)
