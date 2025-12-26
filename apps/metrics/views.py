import hashlib
import hmac
import time
from typing import Any

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from loguru import logger

from config.app_settings import settings
from apps.metrics.utils import record_event
from core.metrics.constants import METRICS_EVENT_TYPES, METRICS_SOURCES


def _validate_hmac(request: HttpRequest, body: bytes) -> tuple[bool, JsonResponse | None]:
    internal_key_id = request.headers.get("X-Key-Id")
    ts_header = request.headers.get("X-TS")
    sig_header = request.headers.get("X-Sig")
    if not all((internal_key_id, ts_header, sig_header)):
        return False, JsonResponse({"detail": "Missing signature headers"}, status=403)

    if internal_key_id != settings.INTERNAL_KEY_ID:
        return False, JsonResponse({"detail": "Unknown key ID"}, status=403)

    try:
        ts = int(str(ts_header))
    except (TypeError, ValueError):
        return False, JsonResponse({"detail": "Invalid timestamp format"}, status=403)

    if abs(time.time() - ts) > 300:
        return False, JsonResponse({"detail": "Stale timestamp"}, status=403)

    secret_key = settings.INTERNAL_API_KEY
    if not secret_key:
        logger.error("metrics_event_denied reason=missing_internal_key")
        return False, JsonResponse({"detail": "Internal auth is not configured"}, status=503)

    message = str(ts).encode() + b"." + body
    expected = hmac.new(secret_key.encode(), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(sig_header or ""), expected):
        return False, JsonResponse({"detail": "Signature mismatch"}, status=403)

    return True, None


@csrf_exempt  # type: ignore[bad-specialization]
@require_POST  # type: ignore[misc]
def record_metrics_event(request: HttpRequest) -> JsonResponse:
    body = request.body or b""
    ok, error_response = _validate_hmac(request, body)
    if not ok:
        return error_response or JsonResponse({"detail": "Unauthorized"}, status=403)
    try:
        import json

        payload: dict[str, Any] = json.loads(body.decode("utf-8") or "{}")
    except Exception:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    event_type = str(payload.get("event_type") or "").strip()
    source = str(payload.get("source") or "").strip()
    source_id = str(payload.get("source_id") or "").strip()
    if event_type not in METRICS_EVENT_TYPES:
        return JsonResponse({"detail": "Invalid event_type"}, status=400)
    if source not in METRICS_SOURCES:
        return JsonResponse({"detail": "Invalid source"}, status=400)
    if not source_id:
        return JsonResponse({"detail": "Missing source_id"}, status=400)

    created = record_event(event_type, source, source_id)
    return JsonResponse({"status": "ok", "created": bool(created)})
