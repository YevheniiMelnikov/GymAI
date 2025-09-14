from django.apps import AppConfig
from core.containers import create_container, set_container, get_container
from core.services.internal import APIService


class WebappConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"  # pyrefly: ignore[bad-override]
    name = "apps.webapp"

    def ready(self) -> None:
        container = create_container()
        set_container(container)
        APIService.configure(get_container)
