from django.db import models
from django.db.models import JSONField, Q

from apps.profiles.models import Profile


class SubscriptionPeriod(models.TextChoices):
    ONE_MONTH = "1m", "1 month"
    SIX_MONTHS = "6m", "6 months"
    TWELVE_MONTHS = "12m", "12 months"


class Program(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="programs")
    exercises_by_day = JSONField(default=list, blank=True)
    split_number = models.IntegerField(null=True, blank=True)
    wishes = models.CharField(max_length=500, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Program"
        verbose_name_plural = "Programs"
        indexes = [
            models.Index(fields=["profile", "-created_at"], name="program_profile_created_idx"),
        ]


class Subscription(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="subscriptions")
    updated_at = models.DateTimeField(auto_now=True)
    enabled = models.BooleanField(default=False)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    period = models.CharField(
        max_length=3,
        choices=SubscriptionPeriod.choices,
        default=SubscriptionPeriod.ONE_MONTH,
    )
    split_number = models.IntegerField(default=3)
    exercises = JSONField(default=list, blank=True, null=True)
    workout_location = models.CharField(
        max_length=32,
        choices=[("gym", "gym"), ("home", "home")],
        default="gym",
    )
    wishes = models.CharField(max_length=500, default="")
    payment_date = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        verbose_name = "Subscription"
        verbose_name_plural = "Subscriptions"
        indexes = [
            models.Index(fields=["profile", "-updated_at"], name="sub_profile_updated_idx"),
            models.Index(
                fields=["profile"],
                name="sub_active_profile_idx",
                condition=Q(enabled=True),
            ),
            models.Index(
                fields=["payment_date"],
                name="sub_paydate_enabled_idx",
                condition=Q(enabled=True),
            ),
        ]
