from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import Model


class Profile(Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    status = models.CharField(max_length=50, default="client")
    language = models.CharField(max_length=50, null=True, blank=True)

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
    payment_details = models.CharField(max_length=50, null=True, blank=True)  # TODO: ADD RATING FIELD

    class Meta:
        verbose_name = "profile"
        verbose_name_plural = "profiles"


class Subscription(models.Model):
    user = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="subscriptions")
    subscription_id = models.AutoField(primary_key=True)
    expire_date = models.DateField()
    enabled = models.BooleanField(default=False)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    training_count = models.IntegerField()

    class Meta:
        verbose_name = "subscription"
        verbose_name_plural = "subscriptions"
