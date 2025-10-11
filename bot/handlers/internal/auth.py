"""Common authentication helpers for internal endpoints."""
from __future__ import annotations

import hmac
from functools import wraps
from typing import Awaitable, Callable, TypeVar

from aiohttp import web
from loguru import logger

from config.app_settings import settings

Handler = TypeVar("Handler", bound=Callable[..., Awaitable[web.StreamResponse]])


def _client_ip(request: web.Request) -> str | None:
    peer = request.transport.get_extra_info("peername") if request.transport else None
    if isinstance(peer, tuple) and peer:
        host = peer[0]
        if isinstance(host, str):
            return host
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return None


def _is_ip_allowed(request: web.Request) -> tuple[bool, str | None]:
    allowlist = [ip for ip in settings.INTERNAL_IP_ALLOWLIST if ip]
    client_ip = _client_ip(request)
    if not allowlist:
        return True, client_ip
    return client_ip in allowlist, client_ip


def require_internal_auth(handler: Handler) -> Handler:
    @wraps(handler)
    async def wrapped(request: web.Request, *args, **kwargs):  # type: ignore[override]
        if settings.DEBUG:
            return await handler(request, *args, **kwargs)

        allowed_ip, client_ip = _is_ip_allowed(request)
        expected_key = settings.INTERNAL_API_KEY or ""
        provided_key = request.headers.get("X-Internal-Api-Key", "")
        has_expected_key = bool(expected_key)
        has_provided_key = bool(provided_key)

        if not allowed_ip:
            logger.warning(
                f"internal_auth_denied path={request.rel_url} client_ip={client_ip or 'unknown'} "
                f"has_internal_key={has_provided_key} reason=ip_not_allowed"
            )
            payload = {"code": "unauthorized", "message": "Unauthorized"}
            return web.json_response(payload, status=401)

        if has_expected_key:
            if has_provided_key and hmac.compare_digest(provided_key, expected_key):
                return await handler(request, *args, **kwargs)
            reason = "missing_key" if not has_provided_key else "key_mismatch"
            logger.warning(
                f"internal_auth_denied path={request.rel_url} client_ip={client_ip or 'unknown'} "
                f"has_internal_key={has_provided_key} reason={reason}"
            )
            payload = {"code": "unauthorized", "message": "Unauthorized"}
            return web.json_response(payload, status=401)

        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Api-Key "):
            fallback_key = authorization.split(" ", 1)[1].strip()
            api_key = settings.API_KEY or ""
            if fallback_key and api_key and hmac.compare_digest(fallback_key, api_key):
                return await handler(request, *args, **kwargs)

        return await handler(request, *args, **kwargs)

    return wrapped  # type: ignore[return-value]
