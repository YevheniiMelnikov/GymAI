from django.contrib.auth.models import User
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import Model, JSONField


class Profile(Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    status = models.CharField(max_length=50, default="client")
    language = models.CharField(max_length=50, null=True, blank=True)
    assigned_to = ArrayField(models.IntegerField(), default=list, blank=True)

    # client fields:
    gender = models.CharField(max_length=50, null=True, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    workout_experience = models.CharField(max_length=50, null=True, blank=True)
    workout_goals = models.CharField(max_length=250, null=True, blank=True)
    health_notes = models.CharField(max_length=250, null=True, blank=True)
    weight = models.IntegerField(null=True, blank=True, validators=[MaxValueValidator(999)])

    # coach fields:
    name = models.CharField(max_length=50, null=True, blank=True)
    work_experience = models.IntegerField(null=True, blank=True, validators=[MaxValueValidator(99)])
    additional_info = models.CharField(max_length=250, null=True, blank=True)
    profile_photo = models.CharField(max_length=250, null=True, blank=True)
    payment_details = models.CharField(max_length=50, null=True, blank=True)
    verified = models.BooleanField(default=False)

    class Meta:
        verbose_name = "profile"
        verbose_name_plural = "profiles"


class Program(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="programs")
    exercises_by_day = JSONField(default=dict, blank=True)
    split_number = models.IntegerField(null=True, blank=True, validators=[MaxValueValidator(7)])
    created_at = models.DateTimeField(auto_now_add=True)

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


class Subscription(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="subscriptions")
    updated_at = models.DateTimeField(auto_now=True)
    enabled = models.BooleanField(default=False)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    workout_days = ArrayField(models.CharField(max_length=100), default=list, blank=True)
    exercises = JSONField(default=dict, blank=True, null=True)

    class Meta:
        verbose_name = "subscription"
        verbose_name_plural = "subscriptions"
