from django.apps import AppConfig
from dependency_injector import providers

from core.containers import create_container, set_container, get_container
from core.infra.payment import BotCoachResolver, BotCreditService, TaskPaymentNotifier
from core.services.internal import APIService


class WebappConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"  # pyrefly: ignore[bad-override]
    name = "apps.webapp"

    def ready(self) -> None:
        container = create_container()
        container.notifier.override(providers.Factory(TaskPaymentNotifier))
        container.credit_service.override(providers.Factory(BotCreditService))
        container.coach_resolver.override(providers.Factory(BotCoachResolver))
        set_container(container)
        APIService.configure(get_container)
