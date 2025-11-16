class Redis:
    def __init__(self):
        self._storage = {}

    async def get(self, key):
        return self._storage.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self._storage:
            return False
        self._storage[key] = value
        return True

    async def exists(self, key):
        return 1 if key in self._storage else 0

    async def expire(self, key, ttl):
        return True

    def pipeline(self):
        return Pipeline(self)

    async def execute(self):
        return True

    @classmethod
    def from_url(cls, *args, **kwargs):
        return cls()


class Pipeline:
    def __init__(self, redis_instance=None):
        self._redis = redis_instance

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False

    async def watch(self, *args, **kwargs):
        return None

    async def multi(self, *args, **kwargs):
        return None

    async def pexpire(self, *args, **kwargs):
        return None

    async def execute(self):
        return []


def from_url(*args, **kwargs):
    return Redis.from_url(*args, **kwargs)


__all__ = ["Redis", "Pipeline", "from_url"]