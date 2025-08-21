from __future__ import annotations

from typing import Any, Callable


class _APIServiceProxy:
    def __init__(self) -> None:
        self._provider: Callable[[], Any] | None = None

    def configure(self, provider: Callable[[], Any]) -> None:
        self._provider = provider

    def _container(self) -> Any:
        if self._provider is None:
            raise RuntimeError("Container provider is not configured")
        return self._provider()

    @property
    def payment(self):
        return self._container().payment_service()

    @property
    def profile(self):
        return self._container().profile_service()

    @property
    def workout(self):
        return self._container().workout_service()

    @property
    def ai_coach(self):
        return self._container().ai_coach_service()


APIService = _APIServiceProxy()
