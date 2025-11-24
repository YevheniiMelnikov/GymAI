from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(ModelAdmin):
    list_display = (  # pyrefly: ignore[bad-override]
        "id",
        "payment_type",
        "profile",
        "amount",
        "status",
        "processed",
        "created_at",
    )
    list_filter = (  # pyrefly: ignore[bad-override]
        "status",
        "processed",
        "payment_type",
        "created_at",
    )
    search_fields = (  # pyrefly: ignore[bad-override]
        "order_id",
        "profile__tg_id",
        "profile__name",
    )
    readonly_fields = ("created_at", "updated_at")  # pyrefly: ignore[bad-override]
