from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from .models import Profile, ClientProfile, CoachProfile


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = "Profile"
    fields = ("status", "language", "current_tg_id", "name", "assigned_to")
    extra = 0


class UserAdminCustom(UserAdmin):
    inlines = (ProfileInline,)
    list_display = ("username", "email", "first_name", "last_name", "is_staff", "get_tg_id")

    def get_tg_id(self, obj):
        return obj.profile.current_tg_id if hasattr(obj, "profile") else None

    get_tg_id.short_description = "Telegram ID"


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "status",
        "current_tg_id",
        "language",
    )
    list_filter = ("status", "language")
    search_fields = ("user__username", "current_tg_id", "name")
    raw_id_fields = ("user",)


@admin.register(ClientProfile)
class ClientProfileAdmin(admin.ModelAdmin):
    list_display = ("profile", "coach", "gender", "born_in", "workout_experience")
    list_filter = ("gender", "workout_experience")
    search_fields = ("profile__user__username", "coach__profile__user__username")
    raw_id_fields = ("profile", "coach")


@admin.register(CoachProfile)
class CoachProfileAdmin(admin.ModelAdmin):
    list_display = ("profile", "surname", "verified", "subscription_price", "program_price")
    list_filter = ("verified",)
    search_fields = ("profile__user__username", "surname")
    raw_id_fields = ("profile",)


admin.site.unregister(User)
admin.site.register(User, UserAdminCustom)
