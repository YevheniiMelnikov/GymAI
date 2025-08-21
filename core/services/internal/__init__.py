from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any, cast


class _LazyServiceProxy:
    def __init__(self, provider: Callable[[], Any]) -> None:
        self._provider: Callable[[], Any] = provider
        self._instance: Any | None = None

    async def _get_instance(self) -> Any:
        if self._instance is None:
            service: Any = self._provider()
            if inspect.isawaitable(service):
                service = await cast(Awaitable[Any], service)
            self._instance = service
        return self._instance

    def __getattr__(self, name: str) -> Callable[..., Awaitable[Any]]:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            instance: Any = await self._get_instance()
            attr: Any = getattr(instance, name)
            result: Any = attr(*args, **kwargs)
            if inspect.isawaitable(result):
                return await cast(Awaitable[Any], result)
            return result

        return wrapper


class _APIServiceProxy:
    def __init__(self) -> None:
        self._provider: Callable[[], Any] | None = None

    def configure(self, provider: Callable[[], Any]) -> None:
        self._provider = provider

    def _container(self) -> Any:
        if self._provider is None:
            raise RuntimeError("Container provider is not configured")
        return self._provider()

    def _service(self, name: str) -> _LazyServiceProxy:
        container: Any = self._container()
        provider: Callable[[], Any] = getattr(container, name)
        return _LazyServiceProxy(provider)

    @property
    def payment(self) -> _LazyServiceProxy:
        return self._service("payment_service")

    @property
    def profile(self) -> _LazyServiceProxy:
        return self._service("profile_service")

    @property
    def workout(self) -> _LazyServiceProxy:
        return self._service("workout_service")

    @property
    def ai_coach(self) -> _LazyServiceProxy:
        return self._service("ai_coach_service")


APIService = _APIServiceProxy()
