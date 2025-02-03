from django.contrib import admin
from .models import Program, Subscription, Payment


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("id", "split_number", "created_at_short", "wishes_short")
    list_filter = ("created_at", "split_number")
    search_fields = ("client_profile__profile__user__email", "client_profile__profile__user__username")
    raw_id_fields = ("client_profile",)
    date_hierarchy = "created_at"

    def created_at_short(self, obj):
        return obj.created_at.strftime("%Y-%m-%d %H:%M")

    created_at_short.short_description = "Created"

    def wishes_short(self, obj):
        return obj.wishes[:50] + "..." if obj.wishes else "-"

    wishes_short.short_description = "Wishes"


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("id", "enabled", "price", "payment_date", "updated_at_short")
    list_filter = ("enabled", "payment_date", "price")
    search_fields = ("client_profile__profile__user__email", "wishes", "payment_date")
    raw_id_fields = ("client_profile",)
    date_hierarchy = "updated_at"

    def updated_at_short(self, obj):
        return obj.updated_at.strftime("%Y-%m-%d %H:%M")

    updated_at_short.short_description = "Last Updated"


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "order_id_short",
        "payment_type",
        "status",
        "amount",
        "profile_email",
        "created_at_short",
        "handled",
    )
    list_filter = ("status", "payment_type", "handled")
    search_fields = ("order_id", "profile__user__email", "profile__user__username")
    raw_id_fields = ("profile",)
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"

    def order_id_short(self, obj):
        return obj.order_id[:15] + "..." if len(obj.order_id) > 15 else obj.order_id

    order_id_short.short_description = "Order ID"

    def profile_email(self, obj):
        return obj.profile.user.email

    profile_email.short_description = "User Email"

    def created_at_short(self, obj):
        return obj.created_at.strftime("%Y-%m-%d %H:%M")

    created_at_short.short_description = "Created"

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields + ("order_id", "amount")
        return self.readonly_fields
