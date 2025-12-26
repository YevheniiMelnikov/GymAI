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


def _is_trusted_proxy(peer_ip: str | None) -> bool:
    trusted = [entry.strip() for entry in settings.INTERNAL_TRUSTED_PROXIES if entry.strip()]
    if not trusted or not peer_ip:
        return False
    try:
        peer_address = ip_address(peer_ip)
    except ValueError:
        logger.debug(f"internal_auth_invalid_proxy_ip peer_ip={peer_ip}")
        return False
    for candidate in trusted:
        try:
            if "/" in candidate:
                network = ip_network(candidate, strict=False)
                if peer_address in network:
                    return True
            else:
                if peer_address == ip_address(candidate):
                    return True
        except ValueError:
            logger.debug(f"internal_auth_invalid_trusted_proxy_entry entry={candidate}")
            continue
    return False


def _client_ip(request: web.Request) -> str | None:
    peer = request.transport.get_extra_info("peername") if request.transport else None
    peer_ip: str | None = None
    if isinstance(peer, tuple) and peer:
        host = peer[0]
        if isinstance(host, str):
            peer_ip = host

    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded and _is_trusted_proxy(peer_ip):
        forwarded_ip = forwarded.split(",")[0].strip()
        if forwarded_ip:
            return forwarded_ip

    real_ip = request.headers.get("X-Real-IP")
    if real_ip and _is_trusted_proxy(peer_ip):
        return real_ip.strip()

    return peer_ip


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


def _parse_api_key_authorization(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, credentials = header.partition(" ")
    if scheme.lower() != "api-key":
        return None
    token = credentials.strip()
    return token or None


def _collect_api_key(request: web.Request) -> str | None:
    internal_header = request.headers.get("X-Internal-Api-Key")
    if internal_header:
        return internal_header.strip() or None
    return _parse_api_key_authorization(request.headers.get("Authorization"))


def require_internal_auth(handler: Handler) -> Handler:
    """Validate internal requests with HMAC-SHA256 signatures and an IP allowlist."""

    @wraps(handler)
    async def wrapped(request: web.Request, *args, **kwargs):  # type: ignore[override]
        is_allowed, client_ip = _is_ip_allowed(request)
        internal_key_id = request.headers.get("X-Key-Id")
        ts_header = request.headers.get("X-TS")
        sig_header = request.headers.get("X-Sig")
        has_signature = bool(internal_key_id or ts_header or sig_header)

        if has_signature:
            if not is_allowed:
                logger.warning(
                    (
                        f"internal_auth_denied reason=ip_not_allowed path={request.rel_url} "
                        f"client_ip={client_ip or 'unknown'}"
                    )
                )
                return web.json_response({"detail": "IP address not allowed"}, status=403)
            if not all((internal_key_id, ts_header, sig_header)):
                logger.warning(
                    (
                        f"internal_auth_denied reason=missing_headers path={request.rel_url} "
                        f"client_ip={client_ip or 'unknown'}"
                    )
                )
                return web.json_response({"detail": "Missing signature headers"}, status=403)

            if internal_key_id != settings.INTERNAL_KEY_ID:
                logger.warning(
                    f"internal_auth_denied reason=unknown_key_id path={request.rel_url} "
                    f"client_ip={client_ip or 'unknown'} key_id={internal_key_id}"
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
                    (
                        f"internal_auth_denied reason=stale_timestamp path={request.rel_url} "
                        f"client_ip={client_ip or 'unknown'}"
                    )
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

        allowlist_enabled = bool(settings.INTERNAL_IP_ALLOWLIST)
        if allowlist_enabled and is_allowed:
            return await handler(request, *args, **kwargs)

        provided_key = _collect_api_key(request)
        internal_api_key = (settings.INTERNAL_API_KEY or "").strip()
        if internal_api_key:
            if provided_key == internal_api_key:
                return await handler(request, *args, **kwargs)
            logger.warning(
                f"internal_auth_denied reason=invalid_internal_api_key path={request.rel_url} "
                f"client_ip={client_ip or 'unknown'}"
            )
            return web.json_response({"detail": "Invalid API key"}, status=401)

        api_key = (settings.API_KEY or "").strip()
        if api_key and provided_key == api_key:
            return await handler(request, *args, **kwargs)

        reason = "missing_api_key" if not provided_key else "invalid_api_key"
        logger.warning(
            f"internal_auth_denied reason={reason} path={request.rel_url} client_ip={client_ip or 'unknown'}"
        )
        return web.json_response({"detail": "Unauthorized"}, status=401)

    return wrapped  # type: ignore[return-value]
