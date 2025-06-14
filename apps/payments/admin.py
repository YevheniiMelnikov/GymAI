from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(ModelAdmin):
    list_display = (
        "id",
        "payment_type",
        "client_profile",
        "amount",
        "status",
        "payout_handled",
        "processed",
        "created_at",
    )
    list_filter = ("status", "payout_handled", "processed", "payment_type", "created_at")
    search_fields = ("order_id", "client_profile__profile__tg_id", "client_profile__name")
    readonly_fields = ("created_at", "updated_at")
