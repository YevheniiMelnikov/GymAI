"""Celery tasks that proxy calls to the bot service."""

from typing import TYPE_CHECKING, TypedDict

import httpx
import orjson
from loguru import logger

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from apps.workout_plans.models import Subscription
from config.app_settings import settings
from core.celery_app import app
from core.internal_http import build_internal_hmac_auth_headers, internal_request_timeout


class WeeklySurveyRecipient(TypedDict):
    profile_id: int
    tg_id: int
    language: str | None
    subscription_id: int


class WeeklySurveyPayload(TypedDict):
    recipients: list[WeeklySurveyRecipient]


__all__ = [
    "send_weekly_survey",
]


def _active_subscriptions_queryset() -> "QuerySet[Subscription]":
    from apps.workout_plans.models import Subscription

    return (
        Subscription.objects.filter(
            enabled=True,
            profile__deleted_at__isnull=True,
            profile__tg_id__isnull=False,
        )
        .order_by("profile_id", "-updated_at")
        .distinct("profile_id")
    )


def _fetch_weekly_survey_recipients() -> list[WeeklySurveyRecipient]:
    recipients: list[WeeklySurveyRecipient] = []
    for row in _active_subscriptions_queryset().values(
        "id",
        "profile_id",
        "profile__tg_id",
        "profile__language",
    ):
        tg_id = row.get("profile__tg_id")
        if tg_id is None:
            continue
        recipients.append(
            {
                "profile_id": int(row["profile_id"]),
                "tg_id": int(tg_id),
                "language": row.get("profile__language"),
                "subscription_id": int(row["id"]),
            }
        )
    return recipients


@app.task(
    bind=True,
    autoretry_for=(httpx.HTTPError,),
    retry_backoff=180,
    retry_jitter=True,
    max_retries=3,
)  # pyrefly: ignore[not-callable]
def send_weekly_survey(self) -> None:
    recipients = _fetch_weekly_survey_recipients()
    if not recipients:
        logger.info("weekly_survey_skipped reason=no_active_subscriptions")
        return

    payload: WeeklySurveyPayload = {"recipients": recipients}
    body = orjson.dumps(payload)
    headers = build_internal_hmac_auth_headers(
        key_id=settings.INTERNAL_KEY_ID,
        secret_key=settings.INTERNAL_API_KEY,
        body=body,
    )
    base_url = settings.BOT_INTERNAL_URL.rstrip("/")
    url = f"{base_url}/internal/tasks/send_weekly_survey/"
    timeout = internal_request_timeout(settings)

    try:
        resp = httpx.post(url, content=body, headers=headers, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(f"Bot call failed for weekly survey: {exc!s}")
        raise self.retry(exc=exc)
