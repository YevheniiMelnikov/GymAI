"""Utilities for authenticated calls to internal bot endpoints."""

from typing import TYPE_CHECKING, Protocol, Union

import httpx


if TYPE_CHECKING:
    from httpx import Timeout as HTTPXTimeout


TimeoutValue = Union["HTTPXTimeout", float]


class _SupportsInternalTimeout(Protocol):
    INTERNAL_HTTP_CONNECT_TIMEOUT: float
    INTERNAL_HTTP_READ_TIMEOUT: float


def build_internal_auth_headers(
    *,
    internal_api_key: str | None,
    fallback_api_key: str | None,
) -> dict[str, str]:
    """Return headers for calls protected by ``require_internal_auth``."""

    headers: dict[str, str] = {}
    trimmed_internal = (internal_api_key or "").strip()
    trimmed_fallback = (fallback_api_key or "").strip()

    if trimmed_internal:
        headers["X-Internal-Api-Key"] = trimmed_internal
    elif trimmed_fallback:
        headers["Authorization"] = f"Api-Key {trimmed_fallback}"

    return headers


def internal_request_timeout(settings: _SupportsInternalTimeout) -> TimeoutValue:
    """Build a timeout configuration for internal bot calls."""

    read_timeout = float(settings.INTERNAL_HTTP_READ_TIMEOUT)
    connect_timeout = float(settings.INTERNAL_HTTP_CONNECT_TIMEOUT)
    timeout_cls = getattr(httpx, "Timeout", None)
    if timeout_cls is not None:
        return timeout_cls(
            read=read_timeout,
            connect=connect_timeout,
            write=read_timeout,
            pool=connect_timeout,
        )
    return read_timeout


__all__ = [
    "build_internal_auth_headers",
    "internal_request_timeout",
]
