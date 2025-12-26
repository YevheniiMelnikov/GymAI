"""Scheduled metrics collection."""

from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from loguru import logger

from apps.metrics.models import MetricsEvent, MetricsEventType
from apps.payments.models import Payment
from config.app_settings import settings
from core.celery_app import app
from core.enums import PaymentStatus
from core.services.gsheets_service import GSheetsService

__all__ = ["collect_weekly_metrics"]


def _coerce_total(value: Decimal | None) -> Decimal:
    return value if value is not None else Decimal("0")


def _start_of_week(dt: datetime) -> datetime:
    start = dt - timedelta(days=dt.weekday())
    return start.replace(hour=0, minute=0, second=0, microsecond=0)


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=300,
    retry_jitter=True,
    max_retries=3,
)  # pyrefly: ignore[not-callable]
def collect_weekly_metrics(self) -> None:
    if not settings.SPREADSHEET_ID:
        logger.warning("weekly_metrics_skipped reason=missing_spreadsheet_id")
        return

    end = _start_of_week(timezone.localtime())
    start = end - timedelta(days=7)

    new_users = MetricsEvent.objects.filter(
        event_type=MetricsEventType.new_user,
        created_at__gte=start,
        created_at__lt=end,
    ).count()
    diet_plans = MetricsEvent.objects.filter(
        event_type=MetricsEventType.diet_plan,
        created_at__gte=start,
        created_at__lt=end,
    ).count()
    ask_ai_answers = MetricsEvent.objects.filter(
        event_type=MetricsEventType.ask_ai_answer,
        created_at__gte=start,
        created_at__lt=end,
    ).count()
    workout_plans = MetricsEvent.objects.filter(
        event_type=MetricsEventType.workout_plan,
        created_at__gte=start,
        created_at__lt=end,
    ).count()

    payments_total = Payment.objects.filter(
        status=PaymentStatus.SUCCESS.value,
        created_at__gte=start,
        created_at__lt=end,
    ).aggregate(total=Sum("amount"))
    total_amount = _coerce_total(payments_total.get("total"))

    row = [
        start.date().isoformat(),
        end.date().isoformat(),
        str(new_users),
        str(diet_plans),
        str(ask_ai_answers),
        str(workout_plans),
        str(total_amount),
    ]
    GSheetsService.append_weekly_metrics(row)
    logger.info(
        "weekly_metrics_sent start={} end={} new_users={} diet_plans={} ask_ai_answers={} "
        "workout_plans={} payments_total={}",
        row[0],
        row[1],
        new_users,
        diet_plans,
        ask_ai_answers,
        workout_plans,
        total_amount,
    )
