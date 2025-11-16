"""Common authentication helpers for internal endpoints."""

import hmac
import time
from functools import wraps
from ipaddress import ip_address, ip_network
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


def require_internal_auth(handler: Handler) -> Handler:
    """Validate internal requests with HMAC-SHA256 signatures and an IP allowlist."""

    @wraps(handler)
    async def wrapped(request: web.Request, *args, **kwargs):  # type: ignore[override]
        is_allowed, client_ip = _is_ip_allowed(request)
        if not is_allowed:
            logger.warning(
                f"internal_auth_denied reason=ip_not_allowed path={request.rel_url} client_ip={client_ip or 'unknown'}"
            )
            return web.json_response({"detail": "IP address not allowed"}, status=403)

        internal_key = settings.INTERNAL_API_KEY or ""
        api_key_header = request.headers.get("Authorization", "")
        shared_key = request.headers.get("X-Internal-Api-Key")
        key_id = request.headers.get("X-Key-Id")
        ts_header = request.headers.get("X-TS")
        sig_header = request.headers.get("X-Sig")

        if not all((key_id, ts_header, sig_header)):
            if internal_key:
                if shared_key == internal_key:
                    return await handler(request, *args, **kwargs)
                if api_key_header == f"Api-Key {internal_key}":
                    return await handler(request, *args, **kwargs)
                if shared_key:
                    return web.json_response({"detail": "Invalid internal key"}, status=401)
            if api_key_header == f"Api-Key {settings.API_KEY}":
                return await handler(request, *args, **kwargs)
            if not internal_key and is_allowed:
                return await handler(request, *args, **kwargs)
            logger.warning(
                f"internal_auth_denied reason=missing_headers path={request.rel_url} client_ip={client_ip or 'unknown'}"
            )
            return web.json_response({"detail": "Missing signature headers"}, status=401)

        if key_id != settings.INTERNAL_KEY_ID:
            logger.warning(
                f"internal_auth_denied reason=unknown_key_id path={request.rel_url} "
                f"client_ip={client_ip or 'unknown'} key_id={key_id}"
            )
            return web.json_response({"detail": "Unknown key ID"}, status=403)

        try:
            ts = int(ts_header)
        except ValueError:
            logger.warning(
                f"internal_auth_denied reason=invalid_ts_format path={request.rel_url} "
                f"client_ip={client_ip or 'unknown'}"
            )
            return web.json_response({"detail": "Invalid timestamp format"}, status=403)

        if abs(time.time() - ts) > 300:
            logger.warning(
                f"internal_auth_denied reason=stale_timestamp path={request.rel_url} client_ip={client_ip or 'unknown'}"
            )
            return web.json_response({"detail": "Stale timestamp"}, status=403)

        body = await request.read()
        message = str(ts).encode() + b"." + body
        expected_sig = hmac.new(settings.INTERNAL_API_KEY.encode(), message, "sha256").hexdigest()

        if not hmac.compare_digest(sig_header, expected_sig):
            logger.warning(
                f"internal_auth_denied reason=signature_mismatch path={request.rel_url} "
                f"client_ip={client_ip or 'unknown'}"
            )
            return web.json_response({"detail": "Signature mismatch"}, status=403)

        return await handler(request, *args, **kwargs)

    return wrapped  # type: ignore[return-value]
