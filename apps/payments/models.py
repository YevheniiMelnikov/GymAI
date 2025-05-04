from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import JSONField

from apps.profiles.models import ClientProfile, Profile


class Program(models.Model):
    client_profile = models.ForeignKey(ClientProfile, on_delete=models.CASCADE, related_name="programs")  # type: ignore
    exercises_by_day = JSONField(default=dict, blank=True)
    split_number = models.IntegerField(null=True, blank=True)  # type: ignore
    wishes = models.CharField(max_length=500, null=True, blank=True)  # type: ignore
    created_at = models.DateTimeField(auto_now_add=True)  # type: ignore

    class Meta:
        verbose_name = "Program"
        verbose_name_plural = "Programs"
        app_label = "apps.payments"


class Subscription(models.Model):
    client_profile = models.ForeignKey(ClientProfile, on_delete=models.CASCADE, related_name="subscriptions")  # type: ignore
    updated_at = models.DateTimeField(auto_now=True)  # type: ignore
    enabled = models.BooleanField(default=False)  # type: ignore
    price = models.DecimalField(max_digits=10, decimal_places=2)  # type: ignore
    workout_days = ArrayField(models.CharField(max_length=100), default=list, blank=True)  # type: ignore
    exercises = JSONField(default=dict, blank=True, null=True)
    wishes = models.CharField(max_length=500, null=True, blank=True)  # type: ignore
    payment_date = models.CharField(max_length=100, null=True, blank=True)  # type: ignore

    class Meta:
        verbose_name = "Subscription"
        verbose_name_plural = "Subscriptions"
        app_label = "apps.payments"


class Payment(models.Model):
    payment_type = models.CharField(max_length=50)  # type: ignore
    handled = models.BooleanField(default=False)  # type: ignore
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="payments")  # type: ignore
    order_id = models.CharField(max_length=100, unique=True)  # type: ignore
    amount = models.DecimalField(max_digits=10, decimal_places=2)  # type: ignore
    status = models.CharField(max_length=50, default="PENDING")  # type: ignore
    error = models.CharField(max_length=250, null=True, blank=True)  # type: ignore
    created_at = models.DateTimeField(auto_now_add=True)  # type: ignore
    updated_at = models.DateTimeField(auto_now=True)  # type: ignore

    class Meta:
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        app_label = "apps.payments"
