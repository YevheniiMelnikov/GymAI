from django.contrib.auth.models import User
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import JSONField, Model


class Profile(Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    status = models.CharField(max_length=50, default="client")
    language = models.CharField(max_length=50, null=True, blank=True)
    assigned_to = ArrayField(models.IntegerField(), default=list, blank=True)
    current_tg_id = models.BigIntegerField(blank=True)
    name = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        verbose_name = "profile"
        verbose_name_plural = "profiles"


class ClientProfile(Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="client_profile")
    coach = models.ForeignKey("CoachProfile", on_delete=models.SET_NULL, null=True, blank=True, related_name="clients")
    gender = models.CharField(max_length=50, null=True, blank=True)
    born_in = models.IntegerField(null=True, blank=True)
    weight = models.IntegerField(null=True, blank=True)
    health_notes = models.CharField(max_length=250, null=True, blank=True)
    workout_experience = models.CharField(max_length=50, null=True, blank=True)
    workout_goals = models.CharField(max_length=250, null=True, blank=True)

    class Meta:
        verbose_name = "client profile"
        verbose_name_plural = "client profiles"


class CoachProfile(Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="coach_profile")
    surname = models.CharField(max_length=50, null=True, blank=True)
    additional_info = models.CharField(max_length=250, null=True, blank=True)
    profile_photo = models.CharField(max_length=250, null=True, blank=True)
    payment_details = models.CharField(max_length=250, null=True, blank=True)
    tax_identification = models.CharField(max_length=250, null=True, blank=True)
    subscription_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    program_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    verified = models.BooleanField(default=False)

    class Meta:
        verbose_name = "coach profile"
        verbose_name_plural = "coach profiles"


class Program(models.Model):
    client_profile = models.ForeignKey(ClientProfile, on_delete=models.CASCADE, related_name="programs")
    exercises_by_day = JSONField(default=dict, blank=True)
    split_number = models.IntegerField(null=True, blank=True)
    wishes = models.CharField(max_length=500, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "program"
        verbose_name_plural = "programs"


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


class Payment(models.Model):
    payment_type = models.CharField(max_length=50)
    handled = models.BooleanField(default=False)
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="payments")
    shop_order_number = models.CharField(max_length=100, unique=True)
    shop_bill_id = models.CharField(max_length=100, null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=50, default="PENDING")
    error = models.CharField(max_length=250, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "payment"
        verbose_name_plural = "payments"
