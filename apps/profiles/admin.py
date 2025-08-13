from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Profile, ClientProfile, CoachProfile


@admin.register(Profile)
class ProfileAdmin(ModelAdmin):
    list_display = ("id", "tg_id", "role", "language")  # pyrefly: ignore[bad-override]
    search_fields = ("tg_id",)  # pyrefly: ignore[bad-override]
    list_filter = ("role", "language")  # pyrefly: ignore[bad-override]


@admin.register(ClientProfile)
class ClientProfileAdmin(ModelAdmin):
    list_display = ("id", "profile", "name", "gender", "born_in")  # pyrefly: ignore[bad-override]
    search_fields = ("name",)  # pyrefly: ignore[bad-override]
    list_filter = ("gender",)  # pyrefly: ignore[bad-override]


@admin.register(CoachProfile)
class CoachProfileAdmin(ModelAdmin):
    list_display = (  # pyrefly: ignore[bad-override]
        "id",
        "profile",
        "name",
        "surname",
        "verified",
        "work_experience",
        "payout_due",
    )
    search_fields = ("name", "surname")  # pyrefly: ignore[bad-override]
    list_filter = ("verified",)  # pyrefly: ignore[bad-override]
