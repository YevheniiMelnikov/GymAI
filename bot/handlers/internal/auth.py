"""Common authentication helpers for internal endpoints."""

from __future__ import annotations

from functools import wraps
from typing import Awaitable, Callable, TypeVar

from aiohttp import web
from loguru import logger

from config.app_settings import settings

Handler = TypeVar("Handler", bound=Callable[..., Awaitable[web.StreamResponse]])


def _is_ip_allowed(request: web.Request) -> bool:
    allowlist = [ip for ip in settings.INTERNAL_IP_ALLOWLIST if ip]
    if not allowlist:
        return True
    peer = request.transport.get_extra_info("peername") if request.transport else None
    remote_ip = peer[0] if isinstance(peer, tuple) and peer else None
    return remote_ip in allowlist


def require_internal_auth(handler: Handler) -> Handler:
    @wraps(handler)
    async def wrapped(request: web.Request, *args, **kwargs):  # type: ignore[override]
        if settings.DEBUG:
            return await handler(request, *args, **kwargs)

        expected_key = settings.INTERNAL_API_KEY or ""
        provided_key = request.headers.get("X-Internal-Api-Key", "")

        if expected_key and provided_key == expected_key and _is_ip_allowed(request):
            return await handler(request, *args, **kwargs)

        logger.warning(f"internal_auth_denied path={request.rel_url} has_key={bool(provided_key)}")
        payload = {"code": "unauthorized", "message": "Unauthorized"}
        return web.json_response(payload, status=401)

    return wrapped  # type: ignore[return-value]
