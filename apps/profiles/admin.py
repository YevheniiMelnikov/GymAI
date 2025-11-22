from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Profile


@admin.register(Profile)
class ProfileAdmin(ModelAdmin):
    list_display = ("id", "tg_id", "language", "status", "credits")  # pyrefly: ignore[bad-override]
    search_fields = ("tg_id", "name")  # pyrefly: ignore[bad-override]
    list_filter = ("language", "status")  # pyrefly: ignore[bad-override]
