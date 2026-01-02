from datetime import datetime
from typing import Any, cast

import httpx
from django.http import HttpRequest, JsonResponse
from loguru import logger

from apps.profiles.models import Profile
from apps.workout_plans.models import Program as ProgramModel
from apps.workout_plans.repos import ProgramRepository
from config.app_settings import settings
from core.schemas import Program as ProgramSchema

from .utils import authenticate, call_repo


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
