from django.apps import AppConfig


class HomeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"  # pyrefly: ignore[bad-override]
    name = "apps.home"
