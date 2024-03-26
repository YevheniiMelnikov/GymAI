from django.db import models
from django.db.models import Model


# class PersonManager(BaseUserManager):
#     def create_user(self, tg_user_id, short_name, password, status, **extra_fields):
#         if not tg_user_id:
#             raise ValueError("The Telegram User ID must be set")
#
#         user = self.model(
#             tg_user_id=tg_user_id, short_name=short_name, password=password, status=status, **extra_fields
#         )
#         user.set_password(password)
#         user.save(using=self._db)
#         return user
#
#     def create_superuser(self, tg_user_id, short_name, password, status, **extra_fields):
#         return self.create_user(tg_user_id, short_name, password, status, **extra_fields)


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
