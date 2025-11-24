from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import Program, Subscription


@admin.register(Program)
class ProgramAdmin(ModelAdmin):
    list_display = ("id", "profile", "split_number", "created_at")  # pyrefly: ignore[bad-override]
    search_fields = ("profile__tg_id",)  # pyrefly: ignore[bad-override]
    list_filter = ("split_number", "created_at")  # pyrefly: ignore[bad-override]
    readonly_fields = ("created_at",)  # pyrefly: ignore[bad-override]


@admin.register(Subscription)
class SubscriptionAdmin(ModelAdmin):
    list_display = (  # pyrefly: ignore[bad-override]
        "id",
        "profile",
        "enabled",
        "price",
        "period",
        "payment_date",
        "updated_at",
    )
    search_fields = ("profile__tg_id",)  # pyrefly: ignore[bad-override]
    list_filter = ("enabled", "updated_at")  # pyrefly: ignore[bad-override]
    readonly_fields = ("updated_at",)  # pyrefly: ignore[bad-override]
