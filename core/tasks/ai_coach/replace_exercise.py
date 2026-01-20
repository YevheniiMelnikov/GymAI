"""Celery task for replacing a single exercise via LLM."""

import asyncio
import json
from string import Template
from pathlib import Path
from typing import Any

from celery import Task
from loguru import logger
from config.app_settings import settings
from core.celery_app import app
from core.ai_coach.exercise_catalog import suggest_replacement_exercises
from apps.webapp.exercise_replace import (
    ReplaceExerciseResponse,
    extract_json_payload,
    format_range,
    is_aux_exercise_entry,
    resolve_exercise_entry,
    resolve_profile_payload,
)

__all__ = [
    "replace_exercise_task",
    "enqueue_exercise_replace_task",
    "replace_subscription_exercise_task",
    "enqueue_subscription_exercise_replace_task",
]

AI_REPLACE_SOFT_LIMIT = settings.AI_COACH_TIMEOUT
AI_REPLACE_TIME_LIMIT = AI_REPLACE_SOFT_LIMIT + 30
PROMPTS_DIR = Path(__file__).resolve().parents[3] / "ai_coach" / "agent" / "prompts"


def _cache_key(task_id: str) -> str:
    return f"exercise_replace:{task_id}"


def _store_status(
    task_id: str,
    profile_id: int,
    status: str,
    *,
    error: str | None = None,
) -> None:
    from django.core.cache import cache

    cache.set(
        _cache_key(task_id),
        {"status": status, "profile_id": profile_id, "error": error},
        timeout=settings.AI_COACH_TIMEOUT,
    )


def _resolve_task_id(task: Task) -> str:
    raw = task.request.id
    return str(raw) if raw is not None else ""


def _build_prompt(
    *,
    exercise_id: str,
    exercise_name: str,
    profile_payload: dict[str, Any],
    exercises_by_day: list[dict[str, Any]],
    language: str,
) -> str:
    prompt_template = Template(_load_prompt("replace_exercise.txt"))
    suggestions = [
        {
            "gif_key": entry.gif_key,
            "canonical": entry.canonical,
            "aliases": list(entry.aliases),
            "category": entry.category,
            "primary_muscles": list(entry.primary_muscles),
            "secondary_muscles": list(entry.secondary_muscles),
        }
        for entry in suggest_replacement_exercises(name_query=exercise_name, limit=25)
    ]
    profile_json = json.dumps(profile_payload, ensure_ascii=False)
    program_json = json.dumps(exercises_by_day, ensure_ascii=False)
    catalog_json = json.dumps(suggestions, ensure_ascii=False)
    return prompt_template.safe_substitute(
        language=language,
        exercise_id=exercise_id,
        exercise_name=exercise_name,
        profile_json=profile_json,
        program_json=program_json,
        catalog_json=catalog_json,
    )


def _load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    return path.read_text(encoding="utf-8")


def _load_system_prompt() -> str:
    return _load_prompt("system_prompt.txt")


def _normalize_sets_detail(sets_detail: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in sets_detail:
        data: dict[str, Any]
        if isinstance(item, dict):
            data = item
        elif hasattr(item, "model_dump"):
            data = item.model_dump()
        else:
            raise ValueError("invalid_sets_detail")
        reps_raw = data.get("reps")
        weight_raw = data.get("weight")
        weight_unit = data.get("weight_unit")
        if not isinstance(reps_raw, (int, str)):
            raise ValueError("invalid_set_values")
        if not isinstance(weight_raw, (int, float, str)):
            raise ValueError("invalid_set_values")
        try:
            reps_value = int(str(reps_raw))
            weight_value = float(str(weight_raw))
        except (TypeError, ValueError):
            raise ValueError("invalid_set_values") from None
        if reps_value < 1 or weight_value < 0:
            raise ValueError("invalid_set_values")
        normalized.append(
            {
                "reps": reps_value,
                "weight": weight_value,
                "weight_unit": str(weight_unit) if weight_unit not in (None, "") else None,
            }
        )
    if not normalized:
        raise ValueError("empty_sets_detail")
    return normalized


def _apply_replacement(
    exercise_entry: dict[str, Any],
    replacement: ReplaceExerciseResponse,
) -> None:
    exercise = replacement.exercise
    name = str(exercise.name or "").strip()
    if not name:
        raise ValueError("empty_exercise_name")

    sets_detail = _normalize_sets_detail(exercise.sets_detail)
    reps_values = [float(item["reps"]) for item in sets_detail]
    weight_values = [float(item["weight"]) for item in sets_detail]
    weight_units = {item["weight_unit"] for item in sets_detail if item["weight_unit"]}
    weight_unit = next(iter(weight_units), None) if weight_units else None

    exercise_entry["name"] = name
    exercise_entry["sets"] = str(len(sets_detail))
    exercise_entry["reps"] = format_range(reps_values)

    weight_summary = None
    if any(value > 0 for value in weight_values):
        weight_summary = format_range(weight_values)
        if weight_unit:
            weight_summary = f"{weight_summary} {weight_unit}"
    exercise_entry["weight"] = weight_summary
    exercise_entry["sets_detail"] = sets_detail
    gif_key = getattr(exercise, "gif_key", None)
    if gif_key:
        exercise_entry["gif_key"] = str(gif_key)


def _request_replacement(
    *,
    profile_id: int,
    plan_label: str,
    plan_id: int,
    exercise_id: str,
    exercise_entry: dict[str, Any],
    exercises_by_day: list[dict[str, Any]],
    language: str,
    profile_payload: dict[str, Any],
) -> ReplaceExerciseResponse:
    from ai_coach.agent.llm_helper import LLMHelper

    prompt = _build_prompt(
        exercise_id=exercise_id,
        exercise_name=str(exercise_entry.get("name") or ""),
        profile_payload=profile_payload,
        exercises_by_day=exercises_by_day,
        language=language,
    )

    client, model_name = LLMHelper.get_completion_client()
    logger.info(
        f"exercise_replace_llm_request profile_id={profile_id} {plan_label}_id={plan_id} "
        f"exercise_id={exercise_id} model={model_name} prompt_len={len(prompt)}"
    )
    response = asyncio.run(
        LLMHelper.call_llm(
            client,
            _load_system_prompt(),
            prompt,
            model=model_name,
            max_tokens=settings.AI_COACH_FIRST_PASS_MAX_TOKENS,
        )
    )
    if not response.choices:
        raise ValueError("empty_llm_response")
    message = response.choices[0].message
    content = getattr(message, "content", "") if message is not None else ""
    if not content:
        raise ValueError("empty_llm_response")
    logger.info(
        f"exercise_replace_llm_response profile_id={profile_id} {plan_label}_id={plan_id} "
        f"exercise_id={exercise_id} model={model_name} raw_len={len(str(content))}"
    )
    parsed = extract_json_payload(str(content))
    return ReplaceExerciseResponse.model_validate(parsed)


def _replace_exercise_impl(profile_id: int, program_id: int, exercise_id: str, task_id: str) -> None:
    from apps.profiles.models import Profile
    from apps.workout_plans.repos import ProgramRepository

    profile = Profile.objects.filter(id=profile_id).first()
    if profile is None:
        raise ValueError("profile_not_found")
    program = ProgramRepository.get_by_id(profile_id, program_id)
    if program is None:
        raise ValueError("program_not_found")
    exercises_by_day = getattr(program, "exercises_by_day", None)
    if not isinstance(exercises_by_day, list):
        raise ValueError("program_invalid")

    exercise_entry = resolve_exercise_entry(exercises_by_day, exercise_id)
    if exercise_entry is None:
        raise ValueError("exercise_not_found")
    if is_aux_exercise_entry(exercise_entry):
        raise ValueError("exercise_not_replaceable")

    replacement = _request_replacement(
        profile_id=profile_id,
        plan_label="program",
        plan_id=program_id,
        exercise_id=exercise_id,
        exercise_entry=exercise_entry,
        exercises_by_day=exercises_by_day,
        language=str(profile.language or "en"),
        profile_payload=resolve_profile_payload(profile),
    )

    _apply_replacement(exercise_entry, replacement)
    ProgramRepository.create_or_update(profile_id, exercises_by_day, instance=program)
    logger.info(
        f"exercise_replace_done profile_id={profile_id} program_id={program_id} "
        f"exercise_id={exercise_id} task_id={task_id}"
    )


def _replace_subscription_exercise_impl(
    profile_id: int,
    subscription_id: int,
    exercise_id: str,
    task_id: str,
) -> None:
    from apps.profiles.models import Profile
    from apps.workout_plans.repos import SubscriptionRepository

    profile = Profile.objects.filter(id=profile_id).first()
    if profile is None:
        raise ValueError("profile_not_found")
    subscription = SubscriptionRepository.get_by_id(profile_id, subscription_id)
    if subscription is None:
        raise ValueError("subscription_not_found")
    exercises_by_day = getattr(subscription, "exercises", None)
    if not isinstance(exercises_by_day, list):
        raise ValueError("subscription_invalid")

    exercise_entry = resolve_exercise_entry(exercises_by_day, exercise_id)
    if exercise_entry is None:
        raise ValueError("exercise_not_found")
    if is_aux_exercise_entry(exercise_entry):
        raise ValueError("exercise_not_replaceable")

    replacement = _request_replacement(
        profile_id=profile_id,
        plan_label="subscription",
        plan_id=subscription_id,
        exercise_id=exercise_id,
        exercise_entry=exercise_entry,
        exercises_by_day=exercises_by_day,
        language=str(profile.language or "en"),
        profile_payload=resolve_profile_payload(profile),
    )

    _apply_replacement(exercise_entry, replacement)
    SubscriptionRepository.update_exercises(profile_id, exercises_by_day, instance=subscription)
    logger.info(
        f"exercise_replace_done profile_id={profile_id} subscription_id={subscription_id} "
        f"exercise_id={exercise_id} task_id={task_id}"
    )


@app.task(
    bind=True,
    queue="ai_coach",
    routing_key="ai_coach",
    acks_late=True,
    task_acks_on_failure_or_timeout=False,
    soft_time_limit=AI_REPLACE_SOFT_LIMIT,
    time_limit=AI_REPLACE_TIME_LIMIT,
)
def replace_exercise_task(  # pyrefly: ignore[valid-type]
    self,
    profile_id: int,
    program_id: int,
    exercise_id: str,
) -> None:
    task_id = _resolve_task_id(self)
    if not task_id:
        logger.error("exercise_replace_missing_task_id")
        return
    _store_status(task_id, profile_id, "processing")
    try:
        _replace_exercise_impl(profile_id, program_id, exercise_id, task_id)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc!s}"
        _store_status(task_id, profile_id, "error", error=detail)
        logger.error(
            f"exercise_replace_failed profile_id={profile_id} program_id={program_id} "
            f"exercise_id={exercise_id} task_id={task_id} error={detail}"
        )
        return
    _store_status(task_id, profile_id, "success")


def enqueue_exercise_replace_task(profile_id: int, program_id: int, exercise_id: str) -> str:
    result = replace_exercise_task.apply_async(  # pyrefly: ignore[not-callable]
        args=[profile_id, program_id, exercise_id],
        queue="ai_coach",
        routing_key="ai_coach",
    )
    return str(result.id) if result and result.id else ""


@app.task(
    bind=True,
    queue="ai_coach",
    routing_key="ai_coach",
    acks_late=True,
    task_acks_on_failure_or_timeout=False,
    soft_time_limit=AI_REPLACE_SOFT_LIMIT,
    time_limit=AI_REPLACE_TIME_LIMIT,
)
def replace_subscription_exercise_task(  # pyrefly: ignore[valid-type]
    self,
    profile_id: int,
    subscription_id: int,
    exercise_id: str,
) -> None:
    task_id = _resolve_task_id(self)
    if not task_id:
        logger.error("exercise_replace_missing_task_id")
        return
    _store_status(task_id, profile_id, "processing")
    try:
        _replace_subscription_exercise_impl(profile_id, subscription_id, exercise_id, task_id)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc!s}"
        _store_status(task_id, profile_id, "error", error=detail)
        logger.error(
            f"exercise_replace_failed profile_id={profile_id} subscription_id={subscription_id} "
            f"exercise_id={exercise_id} task_id={task_id} error={detail}"
        )
        return
    _store_status(task_id, profile_id, "success")


def enqueue_subscription_exercise_replace_task(profile_id: int, subscription_id: int, exercise_id: str) -> str:
    result = replace_subscription_exercise_task.apply_async(  # pyrefly: ignore[not-callable]
        args=[profile_id, subscription_id, exercise_id],
        queue="ai_coach",
        routing_key="ai_coach",
    )
    return str(result.id) if result and result.id else ""
