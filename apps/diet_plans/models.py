from django.db import models
from django.db.models import JSONField

from apps.profiles.models import Profile


class DietPlan(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="diet_plans")
    request_id = models.CharField(max_length=64, unique=True)
    plan = JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Diet plan"
        verbose_name_plural = "Diet plans"
        indexes = [
            models.Index(fields=["profile", "-created_at"], name="diet_plan_profile_created_idx"),
            models.Index(fields=["request_id"], name="diet_plan_request_idx"),
        ]
