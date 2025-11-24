import asyncio
import hashlib
import hmac
import inspect
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar, cast
from urllib.parse import parse_qsl

from asgiref.sync import sync_to_async
from django.http import HttpRequest, JsonResponse
from loguru import logger
from rest_framework.exceptions import NotFound

from apps.profiles.models import Profile
from config.app_settings import settings
from core.payment.providers.liqpay import LiqPayGateway

from apps.profiles.repos import ProfileRepository

T = TypeVar("T")


@dataclass(frozen=True)
class AuthResult:
    profile: Profile | None
    error: JsonResponse | None


async def ensure_container_ready() -> None:
    try:
        from core.containers import get_container

        container = get_container()
    except Exception:  # pragma: no cover - optional in tests
        return
    if hasattr(container, "init_resources"):
        maybe = container.init_resources()
        if asyncio.iscoroutine(maybe):
            await maybe


async def call_repo(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Execute repository call regardless of sync_to_async stubbing."""
    result = sync_to_async(func)(*args, **kwargs)
    if inspect.isawaitable(result):
        return await cast(Awaitable[T], result)
    return cast(T, result)


def read_init_data(request: HttpRequest) -> str:
    init_data_raw = request.GET.get("init_data", "")
    init_data: str = str(init_data_raw or "")
    if init_data:
        return init_data

    headers = getattr(request, "headers", None)
    if headers is not None:
        header_value = headers.get("X-Telegram-InitData")
        if header_value:
            return str(header_value)

    meta_value = request.META.get("HTTP_X_TELEGRAM_INITDATA")
    if isinstance(meta_value, str):
        return meta_value
    return ""


async def authenticate(request: HttpRequest) -> AuthResult:
    """
    Verify Telegram init_data and resolve tg_id -> Profile.

    Returns (profile | None, error_response | None).
    """
    init_data: str = read_init_data(request)
    logger.debug(f"Webapp request: init_data length={len(init_data)}")
    try:
        data: dict[str, Any] = verify_init_data(init_data)
    except Exception as exc:
        logger.warning(f"Init data verification failed: {exc} | length={len(init_data)}")
        return AuthResult(None, JsonResponse({"error": "unauthorized"}, status=403))

    user_info: dict[str, Any] = data.get("user", {})  # type: ignore[arg-type]
    tg_id: int = int(str(user_info.get("id", "0")))
    profile: Profile | None = None

    try:
        profile = await call_repo(ProfileRepository.get_by_telegram_id, tg_id)
    except Exception as exc:
        if exc.__class__ is NotFound:
            profile_id = getattr(profile, "id", None)
            logger.warning(f"Client profile not found for profile_id={profile_id}")
            return AuthResult(None, JsonResponse({"error": "not_found"}, status=404))
        raise

    return AuthResult(profile, None)


def parse_program_id(request: HttpRequest) -> tuple[int | None, JsonResponse | None]:
    raw = request.GET.get("program_id")
    if not isinstance(raw, str) or not raw:
        return None, None
    try:
        return int(raw), None
    except ValueError:
        logger.warning(f"Invalid program_id={raw}")
        return None, JsonResponse({"error": "bad_request"}, status=400)


def build_payment_gateway() -> LiqPayGateway:
    return LiqPayGateway(
        settings.PAYMENT_PUB_KEY,
        settings.PAYMENT_PRIVATE_KEY,
        server_url=settings.PAYMENT_CALLBACK_URL,
        result_url=settings.BOT_LINK,
        email=settings.EMAIL,
        checkout_url=settings.CHECKOUT_URL,
    )


def _hash_webapp(token: str, check_string: str) -> str:
    secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()


def _hash_legacy(token: str, check_string: str) -> str:
    secret = hashlib.sha256(token.encode("utf-8")).digest()
    return hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_init_data(init_data: str) -> dict[str, object]:
    items = dict(parse_qsl(init_data, keep_blank_values=True))

    received_hash = (items.pop("hash", "") or "").lower()
    if not received_hash:
        raise ValueError("Invalid init data")

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(items.items()))
    token: str = settings.BOT_TOKEN or ""
    if not token:
        raise ValueError("Invalid init data")

    calc_new = _hash_webapp(token, check_string)
    ok_new = hmac.compare_digest(calc_new, received_hash)

    if not ok_new:
        calc_old = _hash_legacy(token, check_string)
        ok_old = hmac.compare_digest(calc_old, received_hash)
    else:
        calc_old = None
        ok_old = False

    if not (ok_new or ok_old):
        logger.error(
            "Init data verification failed",
            hash_preview=received_hash[:16],
            calc_new_preview=(calc_new or "")[:16],
            calc_old_preview=(calc_old or "")[:16],
        )
        raise ValueError("Invalid init data")

    result: dict[str, object] = {}
    for k, v in items.items():
        if k in {"user", "chat", "receiver"}:
            try:
                result[k] = json.loads(v)
            except Exception:
                result[k] = v
        else:
            result[k] = v

    return result


STATIC_VERSION_FILE: Path = Path(__file__).resolve().parents[2] / "VERSION"


def _resolve_static_version() -> str:
    if settings.DEBUG:
        return str(int(time.time()))

    env_value: str | None = os.getenv("STATIC_VERSION")
    if STATIC_VERSION_FILE.exists():
        version: str = STATIC_VERSION_FILE.read_text(encoding="utf-8").strip()
        if version:
            return version
    if env_value:
        return env_value
    return str(int(time.time()))


STATIC_VERSION: str = _resolve_static_version()


def transform_days(exercises_by_day: list) -> list[dict]:
    days = []
    for idx, day_data in enumerate(exercises_by_day, start=1):
        exercises = []
        for ex_idx, ex_data in enumerate(day_data.get("exercises", [])):
            weight_str = ex_data.get("weight")
            weight = None
            if weight_str:
                parts = str(weight_str).split(" ", 1)
                if len(parts) == 2:
                    weight = {"value": parts[0], "unit": parts[1]}
                else:
                    weight = {"value": weight_str, "unit": ""}

            exercises.append(
                {
                    "id": str(ex_data.get("set_id") or f"ex-{idx}-{ex_idx}"),
                    "name": ex_data.get("name", ""),
                    "sets": ex_data.get("sets"),
                    "reps": ex_data.get("reps"),
                    "weight": weight,
                    "equipment": None,
                    "notes": None,
                }
            )

        days.append(
            {
                "id": f"day-{idx}",
                "index": idx,
                "type": "workout",
                "title": day_data.get("day"),
                "exercises": exercises,
            }
        )
    return days
