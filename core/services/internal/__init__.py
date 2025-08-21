from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable


class _ServiceProxy:
    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._instance: Any | None = None
        self._lock = asyncio.Lock()

    async def _get_instance(self) -> Any:
        if self._instance is None:
            async with self._lock:
                if self._instance is None:
                    obj = self._factory()
                    if inspect.isawaitable(obj):
                        obj = await obj
                    self._instance = obj
        return self._instance

    def __getattr__(self, item: str):
        async def caller(*args: Any, **kwargs: Any):
            service = await self._get_instance()
            attr = getattr(service, item)
            result = attr(*args, **kwargs)
            if inspect.isawaitable(result):
                return await result
            return result

        return caller


class _APIServiceProxy:
    def __init__(self) -> None:
        self._provider: Callable[[], Any] | None = None
        self._proxies: dict[str, _ServiceProxy] = {}

    def configure(self, provider: Callable[[], Any]) -> None:
        self._provider = provider
        self._proxies.clear()

    def _container(self) -> Any:
        if self._provider is None:
            raise RuntimeError("Container provider is not configured")
        return self._provider()

    def _proxy(self, name: str) -> _ServiceProxy:
        if name not in self._proxies:
            container = self._container()
            factory = getattr(container, f"{name}_service")
            self._proxies[name] = _ServiceProxy(factory)
        return self._proxies[name]

    @property
    def payment(self) -> _ServiceProxy:
        return self._proxy("payment")

    @property
    def profile(self) -> _ServiceProxy:
        return self._proxy("profile")

    @property
    def workout(self) -> _ServiceProxy:
        return self._proxy("workout")

    @property
    def ai_coach(self) -> _ServiceProxy:
        return self._proxy("ai_coach")


APIService = _APIServiceProxy()
