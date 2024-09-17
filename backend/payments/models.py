from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import JSONField

from accounts.models import ClientProfile, Profile


class Program(models.Model):
    client_profile = models.ForeignKey(ClientProfile, on_delete=models.CASCADE, related_name="programs")
    exercises_by_day = JSONField(default=dict, blank=True)
    split_number = models.IntegerField(null=True, blank=True)
    wishes = models.CharField(max_length=500, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "program"
        verbose_name_plural = "programs"
        app_label = "payments"


class Subscription(models.Model):
    client_profile = models.ForeignKey(ClientProfile, on_delete=models.CASCADE, related_name="subscriptions")
    updated_at = models.DateTimeField(auto_now=True)
    enabled = models.BooleanField(default=False)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    workout_days = ArrayField(models.CharField(max_length=100), default=list, blank=True)
    exercises = JSONField(default=dict, blank=True, null=True)
    wishes = models.CharField(max_length=500, null=True, blank=True)
    payment_date = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        verbose_name = "subscription"
        verbose_name_plural = "subscriptions"
        app_label = "payments"


class Payment(models.Model):
    payment_type = models.CharField(max_length=50)
    handled = models.BooleanField(default=False)
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="payments")
    order_id = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=50, default="PENDING")
    error = models.CharField(max_length=250, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "payment"
        verbose_name_plural = "payments"
        app_label = "payments"
