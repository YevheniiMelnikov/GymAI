import asyncio
import hashlib
import hmac
import inspect
import json
import os
import time
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar, cast
from urllib.parse import parse_qsl, quote

from asgiref.sync import sync_to_async
from django.http import HttpRequest, JsonResponse
from loguru import logger
from rest_framework.exceptions import NotFound

from apps.profiles.models import Profile
from config.app_settings import settings
from core.payment.providers.liqpay import LiqPayGateway

from apps.profiles.repos import ProfileRepository
from core.ai_coach.exercise_catalog import search_exercises
from core.services.gstorage_service import ExerciseGIFStorage

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


async def authenticate(request: HttpRequest, *, log_request: bool = True) -> AuthResult:
    """
    Verify Telegram init_data and resolve tg_id -> Profile.

    Returns (profile | None, error_response | None).
    """
    init_data: str = read_init_data(request)
    if log_request:
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


def parse_subscription_id(request: HttpRequest) -> tuple[int | None, JsonResponse | None]:
    raw = request.GET.get("subscription_id")
    if not isinstance(raw, str) or not raw:
        return None, None
    try:
        return int(raw), None
    except ValueError:
        logger.warning(f"Invalid subscription_id={raw}")
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

    auth_date_raw = items.get("auth_date")
    if not auth_date_raw:
        env_mode = str(settings.ENVIRONMENT or "development").lower()
        if env_mode == "production":
            raise ValueError("Missing auth_date")
        logger.warning("Init data missing auth_date; skipping TTL check in non-production")
    else:
        try:
            auth_date = int(str(auth_date_raw))
        except ValueError as exc:
            raise ValueError("Invalid auth_date") from exc
        max_age = int(settings.WEBAPP_INIT_DATA_MAX_AGE_SEC or 0)
        now = int(time.time())
        if auth_date > now + 60:
            raise ValueError("auth_date is in the future")
        if max_age > 0 and now - auth_date > max_age:
            raise ValueError("auth_date is too old")

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
WEBAPP_STATIC_DIR: Path = Path(__file__).resolve().parent / "static"


def _bundle_signature() -> str | None:
    """
    Build a lightweight signature from critical webapp assets.

    This allows us to bust caches even when STATIC_VERSION stays unchanged.
    """
    bundle_candidates = [
        WEBAPP_STATIC_DIR / "js-build-v2/index.js",
        WEBAPP_STATIC_DIR / "css/common.css",
    ]
    hasher = hashlib.sha256()
    found = False
    for candidate in bundle_candidates:
        if candidate.exists():
            hasher.update(candidate.read_bytes())
            found = True
    if not found:
        return None
    return hasher.hexdigest()[:10]


def _resolve_static_version() -> str:
    if settings.DEBUG:
        return str(int(time.time()))

    env_value: str | None = os.getenv("STATIC_VERSION")
    version_file_value: str | None = None
    if STATIC_VERSION_FILE.exists():
        version_candidate = STATIC_VERSION_FILE.read_text(encoding="utf-8").strip()
        if version_candidate and version_candidate.lower() != "dev":
            version_file_value = version_candidate

    base_version = env_value or version_file_value
    signature = _bundle_signature()
    if base_version and signature:
        return f"{base_version}-{signature}"
    if base_version:
        return base_version
    if signature:
        return signature
    return str(int(time.time()))


STATIC_VERSION: str = _resolve_static_version()


@lru_cache(maxsize=1)
def _get_gif_storage() -> ExerciseGIFStorage:
    return ExerciseGIFStorage(settings.EXERCISE_GIF_BUCKET)


def transform_days(exercises_by_day: list) -> list[dict]:
    days = []
    storage = _get_gif_storage()
    has_bucket = storage.bucket is not None
    total_exercises = 0
    with_gif_key = 0
    with_gif_url = 0
    proxy_urls = 0
    missing_url_samples: list[str] = []
    sample_url: str | None = None
    sample_key: str | None = None
    for idx, day_data in enumerate(exercises_by_day, start=1):
        exercises = []
        for ex_idx, ex_data in enumerate(day_data.get("exercises", [])):
            total_exercises += 1
            weight_str = ex_data.get("weight")
            weight = None
            if weight_str:
                parts = str(weight_str).split(" ", 1)
                if len(parts) == 2:
                    weight = {"value": parts[0], "unit": parts[1]}
                else:
                    weight = {"value": weight_str, "unit": ""}

            gif_key = ex_data.get("gif_key")
            if not gif_key:
                name_query = str(ex_data.get("name") or "").strip()
                if name_query:
                    matches = search_exercises(name_query=name_query, limit=1)
                    if matches:
                        gif_key = matches[0].gif_key
            if gif_key:
                with_gif_key += 1
            gif_url = None
            if gif_key and has_bucket:
                gif_url = f"/api/gif/{quote(str(gif_key))}"
            if gif_url:
                with_gif_url += 1
                proxy_urls += 1
                if sample_url is None:
                    sample_url = gif_url
                    sample_key = str(gif_key)
            elif gif_key and len(missing_url_samples) < 3:
                missing_url_samples.append(str(gif_key))

            exercises.append(
                {
                    "id": str(ex_data.get("set_id") or f"ex-{idx}-{ex_idx}"),
                    "name": ex_data.get("name", ""),
                    "sets": ex_data.get("sets"),
                    "reps": ex_data.get("reps"),
                    "weight": weight,
                    "sets_detail": ex_data.get("sets_detail"),
                    "equipment": None,
                    "notes": None,
                    "gif_key": str(gif_key) if gif_key else None,
                    "gif_url": gif_url,
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
    logger.info(
        "webapp_gif_urls total_exercises={} with_gif_key={} with_gif_url={} has_bucket={} proxy={} missing_samples={}",
        total_exercises,
        with_gif_key,
        with_gif_url,
        has_bucket,
        proxy_urls,
        ",".join(missing_url_samples) or "none",
    )
    if sample_url:
        logger.info(
            "webapp_gif_sample gif_key={} gif_url={}",
            sample_key,
            sample_url,
        )
    return days
