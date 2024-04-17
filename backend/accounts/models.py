from django.contrib.auth.models import User
from django.db import models
from django.db.models import Model


class Person(Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    status = models.CharField(max_length=50, default="client")
    gender = models.CharField(max_length=50, null=True, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    language = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        verbose_name = "person"
        verbose_name_plural = "persons"


class Subscription(models.Model):
    user = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="subscriptions")
    subscription_id = models.AutoField(primary_key=True)
    expire_date = models.DateField()
    enabled = models.BooleanField(default=False)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    training_count = models.IntegerField()

    class Meta:
        verbose_name = "subscription"
        verbose_name_plural = "subscriptions"
