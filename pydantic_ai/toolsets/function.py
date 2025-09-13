"""Function toolset stub with no registration logic."""

from __future__ import annotations

from typing import Callable, TypeVar, Any

F = TypeVar("F", bound=Callable[..., Any])


class FunctionToolset:
    """Return functions unchanged but keep decorator API."""

    def tool(self, func: F | None = None) -> F | Callable[[F], F]:
        if func is None:

            def decorator(f: F) -> F:
                return f

            return decorator
        return func
