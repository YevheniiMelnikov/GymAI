from django.apps import AppConfig


class WebappConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"  # pyrefly: ignore[bad-override]
    name = "apps.webapp"
