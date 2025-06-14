from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import Program, Subscription


@admin.register(Program)
class ProgramAdmin(ModelAdmin):
    list_display = ("id", "client_profile", "split_number", "created_at")
    search_fields = ("client_profile__profile__tg_id",)
    list_filter = ("split_number", "created_at")
    readonly_fields = ("created_at",)


@admin.register(Subscription)
class SubscriptionAdmin(ModelAdmin):
    list_display = ("id", "client_profile", "enabled", "price", "payment_date", "updated_at")
    search_fields = ("client_profile__profile__tg_id",)
    list_filter = ("enabled", "updated_at")
    readonly_fields = ("updated_at",)
