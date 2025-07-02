from django.db import models
from django.db.models import JSONField
from django.contrib.postgres.fields import ArrayField

from apps.profiles.models import ClientProfile


class SubscriptionPeriod(models.TextChoices):
    FOURTEEN_DAYS = "14d", "14 days"
    ONE_MONTH = "1m", "1 month"
    SIX_MONTHS = "6m", "6 months"


class Program(models.Model):
    client_profile = models.ForeignKey(ClientProfile, on_delete=models.CASCADE, related_name="programs")
    exercises_by_day = JSONField(default=dict, blank=True)
    split_number = models.IntegerField(null=True, blank=True)
    wishes = models.CharField(max_length=500, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Program"
        verbose_name_plural = "Programs"


class Subscription(models.Model):
    client_profile = models.ForeignKey(ClientProfile, on_delete=models.CASCADE, related_name="subscriptions")
    updated_at = models.DateTimeField(auto_now=True)
    enabled = models.BooleanField(default=False)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    period = models.CharField(
        max_length=3,
        choices=SubscriptionPeriod.choices,
        default=SubscriptionPeriod.ONE_MONTH,
    )
    workout_days = ArrayField(models.CharField(max_length=100), default=list, blank=True)
    exercises = JSONField(default=dict, blank=True, null=True)
    wishes = models.CharField(max_length=500, null=True, blank=True)
    payment_date = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        verbose_name = "Subscription"
        verbose_name_plural = "Subscriptions"
