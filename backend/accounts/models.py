from django.db import models
from django.db.models import Model


class Person(Model):
    tg_user_id = models.BigIntegerField(null=False, primary_key=True, blank=False, unique=True)
    short_name = models.CharField(max_length=50, null=False, blank=False)
    password = models.CharField(max_length=50, null=False, blank=False)
    status = models.CharField(max_length=50, default="client")
    tg_chat_id = models.CharField(null=False, blank=False)
    gender = models.CharField(max_length=50, null=True, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    language = models.CharField(max_length=50, null=True, blank=True)

    USERNAME_FIELD = "tg_user_id"
    REQUIRED_FIELDS = ["short_name", "password", "status"]

    class Meta:
        ordering = ["tg_user_id"]
