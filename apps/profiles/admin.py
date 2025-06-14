from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Profile, ClientProfile, CoachProfile


@admin.register(Profile)
class ProfileAdmin(ModelAdmin):
    list_display = ("id", "tg_id", "status", "language")
    search_fields = ("tg_id",)
    list_filter = ("status", "language")


@admin.register(ClientProfile)
class ClientProfileAdmin(ModelAdmin):
    list_display = ("id", "profile", "name", "gender", "born_in")
    search_fields = ("name",)
    list_filter = ("gender",)


@admin.register(CoachProfile)
class CoachProfileAdmin(ModelAdmin):
    list_display = ("id", "profile", "name", "surname", "verified", "work_experience")
    search_fields = ("name", "surname")
    list_filter = ("verified",)
