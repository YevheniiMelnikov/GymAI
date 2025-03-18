from django.contrib import admin

from .models import Profile, ClientProfile, CoachProfile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "tg_id", "language", "name")
    list_filter = ("status", "language")
    search_fields = ("tg_id", "name")


@admin.register(ClientProfile)
class ClientProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "profile", "coach", "gender", "born_in", "workout_experience")
    list_filter = ("gender", "workout_experience")
    search_fields = ("profile__name", "coach__profile__name")


@admin.register(CoachProfile)
class CoachProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "profile", "surname", "verified", "subscription_price", "program_price")
    list_filter = ("verified",)
    search_fields = ("profile__name", "surname")
