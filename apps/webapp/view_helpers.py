from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, TypedDict, cast

import httpx
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from loguru import logger

from apps.profiles.models import Profile
from apps.profiles.choices import WorkoutExperience
from core.enums import Language
from apps.workout_plans.models import Program as ProgramModel, Subscription as SubscriptionModel
from apps.workout_plans.repos import ProgramRepository, SubscriptionRepository
from config.app_settings import settings
from core.enums import SubscriptionPeriod, WorkoutPlanType, WorkoutLocation
from core.schemas import Program as ProgramSchema

from .utils import authenticate, call_repo
from .schemas import WorkoutPlanPricing
from .workout_flow import WorkoutPlanRequest


DIET_PRODUCT_OPTIONS: tuple[str, ...] = (
    "plant_food",
    "meat",
    "fish_seafood",
    "eggs",
    "dairy",
)


class ProfileUpdateData(TypedDict, total=False):
    health_notes: str | None
    workout_goals: str | None
    diet_allergies: str | None
    born_in: int | None
    weight: int | None
    height: int | None
    workout_experience: str | None
    workout_location: str | None
    gender: str | None
    diet_products: list[str] | None
    language: str | None


class ProfileUpdateError(TypedDict, total=False):
    error: str
    field: str
    max: int


async def resolve_profile(
    request: HttpRequest,
    *,
    log_request: bool = True,
) -> Profile | JsonResponse:
    try:
        auth_ctx = await authenticate(request, log_request=log_request)
    except Exception:
        logger.exception("Auth resolution failed")
        return JsonResponse({"error": "server_error"}, status=500)
    if auth_ctx.error:
        return auth_ctx.error
    if auth_ctx.profile is None:
        return JsonResponse({"error": "not_found"}, status=404)
    return auth_ctx.profile


def normalize_support_contact(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    lowered = value.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return value
    if value.startswith("@"):
        value = value[1:]
    if value.startswith("t.me/") or value.startswith("telegram.me/"):
        return f"https://{value}"
    return f"https://t.me/{value}"


def build_support_contact_payload() -> dict[str, str]:
    normalized = normalize_support_contact(settings.TG_SUPPORT_CONTACT)
    url = normalized or settings.TG_SUPPORT_CONTACT or ""
    return {"url": url}


def parse_timestamp(raw: Any) -> int:
    if isinstance(raw, datetime):
        return int(raw.timestamp())
    try:
        return int(float(raw or 0))
    except (TypeError, ValueError):
        try:
            return int(datetime.fromisoformat(str(raw)).timestamp())
        except Exception:
            return 0


def build_days_payload(exercises_by_day: list[Any]) -> list[dict[str, Any]]:
    days_payload: list[dict[str, Any]] = []
    for item in exercises_by_day:
        if hasattr(item, "model_dump"):
            days_payload.append(item.model_dump())
        elif isinstance(item, dict):
            days_payload.append(item)
    if not days_payload:
        days_payload = cast(list[dict[str, Any]], exercises_by_day)
    return days_payload


async def fetch_program(profile_id: int, program_id: int | None) -> ProgramSchema | None:
    program_obj: ProgramModel | ProgramSchema | None = None
    try:
        program_obj = cast(
            ProgramSchema | None,
            await call_repo(ProgramRepository.get_by_id, profile_id, program_id)
            if program_id is not None
            else await call_repo(ProgramRepository.get_latest, profile_id),
        )
    except Exception:
        logger.exception(f"Failed to load program from repo profile_id={profile_id} program_id={program_id}")

    if program_obj is None:
        try:
            all_programs = cast(list[ProgramSchema], await call_repo(ProgramRepository.get_all, profile_id))
            program_obj = all_programs[0] if all_programs else None
        except Exception:
            logger.exception(f"Fallback load of all programs failed profile_id={profile_id}")

    if program_obj is None:
        try:
            program_obj = await call_repo(
                lambda pid: ProgramModel.objects.filter(profile_id=pid).order_by("-created_at", "-id").first(),
                profile_id,
            )
            if program_obj is None:
                await call_repo(lambda pid: ProgramModel.objects.filter(profile_id=pid).count(), profile_id)
            else:
                program_pk = getattr(program_obj, "id", None)
                logger.info(f"Program loaded via direct ORM profile_id={profile_id} program_id={program_pk}")
        except Exception:
            logger.exception(f"Direct program lookup failed profile_id={profile_id}")

    if isinstance(program_obj, ProgramModel):
        try:
            program_obj = ProgramSchema.model_validate(program_obj)
        except Exception:
            logger.exception(f"Failed to normalize ProgramModel for profile_id={profile_id}")
            program_obj = None

    return program_obj


def build_profile_payload(profile: Profile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "tg_id": profile.tg_id,
        "language": profile.language or settings.DEFAULT_LANG,
        "status": profile.status,
    }


def build_webapp_profile_payload(profile: Profile) -> dict[str, Any]:
    def normalize_optional_text(value: object | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text == "-":
            return None
        return text

    return {
        "id": profile.id,
        "tg_id": profile.tg_id,
        "language": profile.language or settings.DEFAULT_LANG,
        "status": profile.status,
        "gender": profile.gender,
        "born_in": profile.born_in,
        "weight": profile.weight,
        "height": profile.height,
        "health_notes": normalize_optional_text(profile.health_notes),
        "workout_experience": profile.workout_experience,
        "workout_goals": normalize_optional_text(profile.workout_goals),
        "diet_allergies": normalize_optional_text(profile.diet_allergies),
        "diet_products": profile.diet_products or [],
        "workout_location": profile.workout_location,
        "credits": profile.credits,
    }


def _read_text(value: object, *, max_len: int) -> tuple[bool, str | None, str | None]:
    if value is None:
        return True, None, None
    if isinstance(value, str):
        cleaned = value.strip()
        if len(cleaned) > max_len:
            return False, None, "profile.error.too_long"
        return True, cleaned or None, None
    return False, None, "bad_request"


def _read_int(value: object) -> tuple[bool, int | None]:
    if value is None or value == "":
        return True, None
    if isinstance(value, bool):
        return False, None
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return False, None
    if parsed < 0:
        return False, None
    return True, parsed


def _read_choice(value: object, allowed: set[str]) -> tuple[bool, str | None]:
    if value is None or value == "":
        return True, None
    if not isinstance(value, str):
        return False, None
    normalized = value.strip().lower()
    if normalized not in allowed:
        return False, None
    return True, normalized


def _read_diet_products(value: object) -> tuple[bool, list[str] | None]:
    if value is None:
        return True, None
    if not isinstance(value, list):
        return False, None
    raw = [str(item).strip() for item in value if str(item).strip()]
    allowed = set(DIET_PRODUCT_OPTIONS)
    unknown = [item for item in raw if item not in allowed]
    if unknown:
        return False, None
    ordered = [item for item in DIET_PRODUCT_OPTIONS if item in raw]
    return True, ordered


def parse_profile_updates(payload: dict[str, Any]) -> tuple[ProfileUpdateData, ProfileUpdateError | None]:
    updates: dict[str, Any] = {}
    text_fields = {
        "health_notes": 250,
        "workout_goals": 250,
        "diet_allergies": 250,
    }
    int_fields = ("born_in", "weight", "height")
    choice_fields = {
        "workout_experience": {choice.value for choice in WorkoutExperience},
        "workout_location": {"gym", "home"},
        "gender": {"male", "female"},
        "language": {lang.value for lang in Language},
    }

    for field_name, max_len in text_fields.items():
        if field_name in payload:
            ok, value, error_key = _read_text(payload.get(field_name), max_len=max_len)
            if not ok:
                error = error_key or "bad_request"
                return cast(ProfileUpdateData, updates), {"error": error, "field": field_name, "max": max_len}
            updates[field_name] = value

    for field_name in int_fields:
        if field_name in payload:
            ok, value = _read_int(payload.get(field_name))
            if not ok:
                return cast(ProfileUpdateData, updates), {"error": "bad_request"}
            updates[field_name] = value

    for field_name, allowed in choice_fields.items():
        if field_name in payload:
            ok, value = _read_choice(payload.get(field_name), allowed)
            if not ok:
                return cast(ProfileUpdateData, updates), {"error": "bad_request"}
            updates[field_name] = value

    if "diet_products" in payload:
        ok, value = _read_diet_products(payload.get("diet_products"))
        if not ok:
            return cast(ProfileUpdateData, updates), {"error": "bad_request"}
        updates["diet_products"] = value

    return cast(ProfileUpdateData, updates), None


def build_workout_plan_options_payload(pricing: WorkoutPlanPricing) -> dict[str, Any]:
    return {
        "program_price": pricing.program_price,
        "subscriptions": [
            {
                "period": option.period.value,
                "months": option.months,
                "price": option.price,
            }
            for option in pricing.subscriptions
        ],
    }


def resolve_workout_plan_required(
    pricing: WorkoutPlanPricing,
    payload: WorkoutPlanRequest,
    *,
    profile_id: int,
) -> int | None:
    if payload.plan_type is WorkoutPlanType.PROGRAM:
        return pricing.program_price

    match = next(
        (option for option in pricing.subscriptions if option.period == payload.period),
        None,
    )
    if match is None:
        logger.warning(f"workout_plan_subscription_period_missing profile_id={profile_id} period={payload.period}")
        return None
    return match.price


async def create_subscription_record(
    *,
    profile: Profile,
    payload: WorkoutPlanRequest,
    required: int,
    workout_location: WorkoutLocation,
    split_number: int,
    wishes: str,
) -> tuple[int | None, int | None]:
    previous_subscription_id: int | None = None
    latest = await call_repo(SubscriptionRepository.get_latest, profile.id)
    if latest is not None and getattr(latest, "enabled", False):
        prev_id = getattr(latest, "id", None)
        if prev_id:
            previous_subscription_id = int(prev_id)

    period_value = payload.period.value if payload.period else SubscriptionPeriod.one_month.value
    amount_value = Decimal(required).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    payment_date = timezone.now().date().isoformat()
    subscription = await call_repo(
        SubscriptionModel.objects.create,
        profile_id=profile.id,
        enabled=False,
        price=amount_value,
        period=period_value,
        split_number=split_number,
        exercises=[],
        workout_location=workout_location.value,
        wishes=wishes,
        payment_date=payment_date,
    )
    subscription_id = int(getattr(subscription, "id", 0) or 0)
    return (subscription_id or None), previous_subscription_id


def resolve_internal_base_url() -> tuple[str, str]:
    raw_base_url = (settings.BOT_INTERNAL_URL or "").rstrip("/")
    fallback_base = f"http://{settings.BOT_INTERNAL_HOST}:{settings.BOT_INTERNAL_PORT}"
    base_url = raw_base_url or fallback_base
    return base_url, fallback_base


async def post_internal_request(
    path: str,
    body: bytes,
    headers: dict[str, str],
    *,
    base_url: str,
    fallback_base: str,
    timeout: float | httpx.Timeout,
    profile_id: int,
    error_label: str,
    retry_label: str,
) -> httpx.Response | None:
    async def _post(target_url: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.post(target_url, content=body, headers=headers)

    path = path.lstrip("/")
    primary_url = f"{base_url}/{path}"
    try:
        return await _post(primary_url)
    except httpx.HTTPError as exc:
        logger.error(f"{error_label} profile_id={profile_id} base_url={base_url} err={exc}")
        if base_url != fallback_base:
            logger.info(f"{retry_label} profile_id={profile_id} fallback={fallback_base}")
            try:
                fallback_url = f"{fallback_base}/{path}"
                return await _post(fallback_url)
            except httpx.HTTPError as exc2:
                logger.error(f"{error_label} profile_id={profile_id} fallback={fallback_base} err={exc2}")
        return None
