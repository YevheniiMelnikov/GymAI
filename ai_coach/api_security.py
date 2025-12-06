import hmac
import time
from typing import Any

from fastapi import HTTPException, Request  # pyrefly: ignore[import-error]
from fastapi.security import HTTPBasicCredentials  # pyrefly: ignore[import-error]
from loguru import logger  # pyrefly: ignore[import-error]

import config.app_settings as app_settings
from config.app_settings import settings
from core.internal_http import resolve_hmac_credentials
from core.utils.redis_lock import get_redis_client


def _get_refresh_settings() -> Any:
    module = globals().get("app_settings")
    if module is not None and hasattr(module, "settings"):
        return getattr(module, "settings")
    return getattr(app_settings, "settings", settings)


def validate_refresh_credentials(credentials: HTTPBasicCredentials) -> None:
    cfg = _get_refresh_settings()
    username = str(credentials.username or "")
    password = str(credentials.password or "")
    expected_user = str(getattr(cfg, "AI_COACH_REFRESH_USER", "") or "")
    expected_pass = str(getattr(cfg, "AI_COACH_REFRESH_PASSWORD", "") or "")
    if username != expected_user or password != expected_pass:
        raise HTTPException(status_code=401, detail="Unauthorized")


async def require_hmac(request: Request) -> None:
    cfg = _get_refresh_settings()
    env_mode = str(getattr(cfg, "ENVIRONMENT", "development")).lower()
    creds = resolve_hmac_credentials(cfg, prefer_ai_coach=True)
    if creds is None:
        if env_mode != "production":
            if not getattr(require_hmac, "_warned_missing", False):
                logger.warning("HMAC credentials missing; skipping validation in non-production mode")
                setattr(require_hmac, "_warned_missing", True)
            return
        raise HTTPException(status_code=503, detail="AI coach HMAC is not configured")
    expected_key_id, secret_key = creds
    key_id = request.headers.get("X-Key-Id")
    ts_header = request.headers.get("X-TS")
    sig_header = request.headers.get("X-Sig")
    if not all((key_id, ts_header, sig_header)):
        raise HTTPException(status_code=403, detail="Missing signature headers")
    if key_id != expected_key_id:
        raise HTTPException(status_code=403, detail="Unknown key ID")
    try:
        ts = int(ts_header) if ts_header is not None else 0
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid timestamp format")
    if abs(time.time() - ts) > 300:
        raise HTTPException(status_code=403, detail="Stale signature")
    body = await request.body()
    message = str(ts).encode() + b"." + body
    expected_sig = hmac.new(secret_key.encode(), message, "sha256").hexdigest()
    if not hmac.compare_digest(expected_sig, sig_header or ""):
        raise HTTPException(status_code=403, detail="Signature mismatch")

    rate_limit = int(getattr(cfg, "AI_COACH_RATE_LIMIT", 0) or 0)
    period = int(getattr(cfg, "AI_COACH_RATE_PERIOD", 0) or 0)
    if rate_limit > 0 and period > 0:
        window = int(time.time() // period)
        key = f"rl:ai:{expected_key_id}:{window}"
        try:
            client = get_redis_client()
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, period)
            if count > rate_limit:
                raise HTTPException(status_code=429, detail="Rate limit exceeded")
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ai_coach_rate_limit_error key_id={} window={} limit={} detail={}",
                expected_key_id,
                window,
                rate_limit,
                exc,
            )
