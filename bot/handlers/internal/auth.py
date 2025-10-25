"""Common authentication helpers for internal endpoints."""

import hmac
from ipaddress import ip_address, ip_network
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
    allowlist = [entry.strip() for entry in settings.INTERNAL_IP_ALLOWLIST if entry.strip()]
    client_ip = _client_ip(request)
    if not allowlist:
        return True, client_ip
    if not client_ip:
        return False, client_ip
    try:
        client_address = ip_address(client_ip)
    except ValueError:
        logger.debug(f"internal_auth_invalid_ip client_ip={client_ip}")
        return False, client_ip

    for candidate in allowlist:
        try:
            if "/" in candidate:
                network = ip_network(candidate, strict=False)
                if client_address in network:
                    return True, client_ip
            else:
                if client_address == ip_address(candidate):
                    return True, client_ip
        except ValueError:
            logger.debug(f"internal_auth_invalid_allowlist_entry entry={candidate}")
            continue
    return False, client_ip


def _extract_api_key(request: web.Request) -> str:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("api-key "):
        return header.split(" ", 1)[1].strip()
    return ""


def require_internal_auth(handler: Handler) -> Handler:
    """Validate bot internal requests with API key headers or IP allowlist.

    When the allowlist is empty, every IP is accepted (useful in local/dev
    environments). Set ``INTERNAL_API_KEY`` and/or the allowlist for
    production deployments.
    """

    @wraps(handler)
    async def wrapped(request: web.Request, *args, **kwargs):  # type: ignore[override]
        if settings.DEBUG:
            return await handler(request, *args, **kwargs)

        allowed_ip, client_ip = _is_ip_allowed(request)
        expected_internal_key = (settings.INTERNAL_API_KEY or "").strip()
        provided_internal_key = (request.headers.get("X-Internal-Api-Key", "") or "").strip()
        provided_auth_key = _extract_api_key(request)
        fallback_api_key = "" if expected_internal_key else (settings.API_KEY or "").strip()
        has_any_key = bool(provided_internal_key or provided_auth_key)

        key_valid = False
        if expected_internal_key:
            if provided_internal_key and hmac.compare_digest(provided_internal_key, expected_internal_key):
                key_valid = True
            elif provided_auth_key and hmac.compare_digest(provided_auth_key, expected_internal_key):
                key_valid = True
        elif fallback_api_key:
            if provided_internal_key and hmac.compare_digest(provided_internal_key, fallback_api_key):
                key_valid = True
            elif provided_auth_key and hmac.compare_digest(provided_auth_key, fallback_api_key):
                key_valid = True

        if key_valid or allowed_ip:
            return await handler(request, *args, **kwargs)

        reason = "ip_not_allowed"
        key_expected = bool(expected_internal_key or fallback_api_key)
        if key_expected:
            reason = "missing_key" if not has_any_key else "key_mismatch"
        elif not client_ip:
            reason = "missing_ip"

        logger.warning(
            f"internal_auth_denied path={request.rel_url} client_ip={client_ip or 'unknown'} "
            f"has_key={has_any_key} allowed_ip={allowed_ip} reason={reason}"
        )
        payload = {"code": "unauthorized", "message": "Unauthorized"}
        return web.json_response(payload, status=401)

    return wrapped  # type: ignore[return-value]
