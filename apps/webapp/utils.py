import asyncio
import hashlib
import hmac
import inspect
import json
from typing import Any, Awaitable, Callable, Protocol, TypeVar, cast
from urllib.parse import parse_qsl

from asgiref.sync import sync_to_async
from django.http import HttpRequest, JsonResponse
from loguru import logger
from rest_framework.exceptions import NotFound

from config.app_settings import settings
from core.payment.providers.liqpay import LiqPayGateway

from apps.profiles.repos import ClientProfileRepository, ProfileRepository

T = TypeVar("T")


class _Profile(Protocol):
    id: int | None
    language: str | None


class _ClientProfile(Protocol):
    id: int | None


AuthResult = tuple[_ClientProfile | None, str, JsonResponse | None, int]


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


async def auth_and_get_client(request: HttpRequest) -> AuthResult:
    """
    Verify Telegram init_data, resolve tg_id -> Profile -> ClientProfile.

    Returns (client | None, language, error_response | None, tg_id).
    """
    init_data: str = read_init_data(request)
    logger.debug(f"Webapp request: init_data length={len(init_data)}")
    lang: str = "eng"
    try:
        data: dict[str, Any] = verify_init_data(init_data)
    except Exception as exc:
        logger.warning(f"Init data verification failed: {exc} | length={len(init_data)}")
        return None, lang, JsonResponse({"error": "unauthorized"}, status=403), 0

    user: dict[str, Any] = data.get("user", {})  # type: ignore[arg-type]
    tg_id: int = int(str(user.get("id", "0")))

    try:
        profile = cast(_Profile, await call_repo(ProfileRepository.get_by_telegram_id, tg_id))
    except Exception as exc:
        if exc.__class__ is NotFound:
            logger.warning(f"Profile not found for tg_id={tg_id}")
            return None, lang, JsonResponse({"error": "not_found"}, status=404), tg_id
        raise

    lang = str(getattr(profile, "language", "eng") or "eng")
    try:
        client = cast(
            _ClientProfile,
            await call_repo(ClientProfileRepository.get_by_profile_id, int(profile.id or 0)),
        )
    except Exception as exc:
        if exc.__class__ is NotFound:
            logger.warning(f"Client profile not found for profile_id={profile.id}")
            return None, lang, JsonResponse({"error": "not_found"}, status=404), tg_id
        raise

    return client, lang, None, tg_id


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
