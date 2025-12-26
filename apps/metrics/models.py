from django.db import models

from django.db.models import Q

from core.metrics.constants import (
    METRICS_EVENT_ASK_AI_ANSWER,
    METRICS_EVENT_DIET_PLAN,
    METRICS_EVENT_NEW_USER,
    METRICS_EVENT_WORKOUT_PLAN,
    METRICS_SOURCE_ASK_AI,
    METRICS_SOURCE_DIET,
    METRICS_SOURCE_PROFILE,
    METRICS_SOURCE_WORKOUT_PLAN,
)


class MetricsEventType(models.TextChoices):
    new_user = METRICS_EVENT_NEW_USER, METRICS_EVENT_NEW_USER
    ask_ai_answer = METRICS_EVENT_ASK_AI_ANSWER, METRICS_EVENT_ASK_AI_ANSWER
    diet_plan = METRICS_EVENT_DIET_PLAN, METRICS_EVENT_DIET_PLAN
    workout_plan = METRICS_EVENT_WORKOUT_PLAN, METRICS_EVENT_WORKOUT_PLAN


class MetricsEventSource(models.TextChoices):
    profile = METRICS_SOURCE_PROFILE, METRICS_SOURCE_PROFILE
    ask_ai = METRICS_SOURCE_ASK_AI, METRICS_SOURCE_ASK_AI
    diet = METRICS_SOURCE_DIET, METRICS_SOURCE_DIET
    workout_plan = METRICS_SOURCE_WORKOUT_PLAN, METRICS_SOURCE_WORKOUT_PLAN


class MetricsEvent(models.Model):
    event_type = models.CharField(max_length=50, choices=MetricsEventType.choices)
    source = models.CharField(max_length=40, choices=MetricsEventSource.choices)
    source_id = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Metrics event"
        verbose_name_plural = "Metrics events"
        indexes = [
            models.Index(fields=["event_type", "created_at"], name="metrics_event_type_created_idx"),
            models.Index(fields=["source", "source_id"], name="metrics_event_source_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["event_type", "source", "source_id"],
                condition=~Q(source_id=""),
                name="metrics_event_unique_source",
            )
        ]
