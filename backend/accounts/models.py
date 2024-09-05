from django.contrib.auth.models import User
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import JSONField, Model


class Profile(Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE) # type: ignore
    status = models.CharField(max_length=50, default="client") # type: ignore
    language = models.CharField(max_length=50, null=True, blank=True) # type: ignore
    assigned_to = ArrayField(models.IntegerField(), default=list, blank=True) # type: ignore
    current_tg_id = models.BigIntegerField(blank=True) # type: ignore

    # client fields:
    gender = models.CharField(max_length=50, null=True, blank=True) # type: ignore
    born_in = models.IntegerField(null=True, blank=True, validators=[MaxValueValidator(2025), MinValueValidator(1900)]) # type: ignore
    workout_experience = models.CharField(max_length=50, null=True, blank=True) # type: ignore
    workout_goals = models.CharField(max_length=250, null=True, blank=True) # type: ignore
    health_notes = models.CharField(max_length=250, null=True, blank=True) # type: ignore
    weight = models.IntegerField(null=True, blank=True, validators=[MaxValueValidator(999)]) # type: ignore

    # coach fields:
    name = models.CharField(max_length=50, null=True, blank=True) # type: ignore
    work_experience = models.IntegerField(null=True, blank=True, validators=[MaxValueValidator(99)]) # type: ignore
    additional_info = models.CharField(max_length=250, null=True, blank=True) # type: ignore
    profile_photo = models.CharField(max_length=250, null=True, blank=True) # type: ignore
    payment_details = models.CharField(max_length=250, null=True, blank=True) # type: ignore
    verified = models.BooleanField(default=False) # type: ignore

    class Meta:
        verbose_name = "profile"
        verbose_name_plural = "profiles"


class Program(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="programs") # type: ignore
    exercises_by_day = JSONField(default=dict, blank=True) # type: ignore
    split_number = models.IntegerField(null=True, blank=True, validators=[MaxValueValidator(7)]) # type: ignore
    created_at = models.DateTimeField(auto_now_add=True) # type: ignore

    @classmethod
    def from_dict(cls, data: dict) -> "Program":
        profile_id = data.get("profile")
        exercises_by_day = data.get("exercises_by_day", {})
        split_number = data.get("split_number", 1)
        program = cls(profile_id=profile_id, exercises_by_day=exercises_by_day, split_number=split_number)
        return program

    class Meta:
        verbose_name = "program"
        verbose_name_plural = "programs"


class Subscription(models.Model): # type: ignore
    id = models.BigAutoField(primary_key=True) # type: ignore
    user = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="subscriptions") # type: ignore
    updated_at = models.DateTimeField(auto_now=True) # type: ignore
    enabled = models.BooleanField(default=False) # type: ignore
    price = models.DecimalField(max_digits=10, decimal_places=2) # type: ignore
    workout_days = ArrayField(models.CharField(max_length=100), default=list, blank=True) # type: ignore
    exercises = JSONField(default=dict, blank=True, null=True) # type: ignore

    class Meta:
        verbose_name = "subscription"
        verbose_name_plural = "subscriptions"


class Payment(models.Model):
    payment_type = models.CharField(max_length=50) # type: ignore
    handled = models.BooleanField(default=False) # type: ignore
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="payments") # type: ignore
    shop_order_number = models.CharField(max_length=100, unique=True) # type: ignore
    shop_bill_id = models.CharField(max_length=100, null=True, blank=True) # type: ignore
    amount = models.DecimalField(max_digits=10, decimal_places=2) # type: ignore
    status = models.CharField(max_length=50, default="PENDING") # type: ignore
    error = models.CharField(max_length=250, null=True, blank=True) # type: ignore
    created_at = models.DateTimeField(auto_now_add=True) # type: ignore
    updated_at = models.DateTimeField(auto_now=True) # type: ignore

    class Meta:
        verbose_name = "payment"
        verbose_name_plural = "payments"
