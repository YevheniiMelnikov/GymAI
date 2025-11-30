"""Utilities for authenticated calls to internal bot endpoints."""

import hmac
import hashlib
import time
from typing import TYPE_CHECKING, Protocol, Union

import httpx


if TYPE_CHECKING:
    from httpx import Timeout as HTTPXTimeout


TimeoutValue = Union["HTTPXTimeout", float]


class _SupportsInternalTimeout(Protocol):
    INTERNAL_HTTP_CONNECT_TIMEOUT: float
    INTERNAL_HTTP_READ_TIMEOUT: float


class _SupportsHMAC(Protocol):
    AI_COACH_INTERNAL_KEY_ID: str
    AI_COACH_INTERNAL_API_KEY: str
    INTERNAL_KEY_ID: str
    INTERNAL_API_KEY: str


def build_internal_hmac_auth_headers(*, key_id: str, secret_key: str, body: bytes) -> dict[str, str]:
    """Return HMAC-signed headers for an internal request."""
    now = str(int(time.time()))
    message = now.encode() + b"." + body
    signature = hmac.new(secret_key.encode(), message, hashlib.sha256).hexdigest()
    return {
        "X-Key-Id": key_id,
        "X-TS": now,
        "X-Sig": signature,
    }


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


def resolve_hmac_credentials(
    settings: _SupportsHMAC,
    *,
    prefer_ai_coach: bool = False,
) -> tuple[str, str] | None:
    """Resolve HMAC credentials from settings.

    prefer_ai_coach=True tries AI_COACH_* first, then falls back to INTERNAL_* for
    compatibility. Callers should enforce production requirements separately.
    """

    key_id: str = ""
    secret_key: str = ""
    if prefer_ai_coach:
        key_id = str(getattr(settings, "AI_COACH_INTERNAL_KEY_ID", "") or "")
        secret_key = str(getattr(settings, "AI_COACH_INTERNAL_API_KEY", "") or "")
    if not key_id:
        key_id = str(getattr(settings, "INTERNAL_KEY_ID", "") or "")
    if not secret_key:
        secret_key = str(getattr(settings, "INTERNAL_API_KEY", "") or "")
    if key_id and secret_key:
        return key_id, secret_key
    return None


__all__ = [
    "build_internal_hmac_auth_headers",
    "resolve_hmac_credentials",
    "internal_request_timeout",
]
